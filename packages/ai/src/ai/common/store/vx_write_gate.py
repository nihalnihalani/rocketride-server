# =============================================================================
# RocketRide Engine
# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""The write gate of the vector store tools. It fails closed.

``remove_document``, ``delete`` and ``upsert`` call :func:`check_write` before
they touch the store. The gate reads who is calling only from the context the
engine attached to the call (``ai.common.tool_context.current_tool_call()``);
nothing in the tool input is ever read as context. It checks, in order:

====================================================  ========================
Condition                                             Result
====================================================  ========================
any objectId is ``'schema'`` (the control record)     ``RESERVED_ID``
no context (or one the gate cannot read)              ``WRITES_UNKNOWN_CALLER``
an agent call and ``agent_writes`` on                 allowed
an agent call and ``agent_writes`` off                ``WRITES_AGENT``
a DAP call and ``allow_writes`` off                   ``WRITES_DISABLED``
a DAP call from a source other than Tools             ``WRITES_SOURCE``
a DAP caller that is not an account or a task key     ``WRITES_PUBLIC``
a DAP call that does not name the node                ``WRITES_BROADCAST``
a DAP ``upsert`` that supplies its own embedding      ``INVALID_INPUT``
otherwise                                             allowed
====================================================  ========================

A refusal is a :class:`~ai.common.store.errors.ToolRefusal`, which the tool
wrapper turns into ``{success: false, code, error}``; nothing is written. On an
engine without ``ai.common.tool_context``, or one that does not attach a
context, every write is refused.

See ``docs/development/nodes/vector-tool-contract.md`` section 6.
"""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from .errors import ToolRefusal
from .vx_types import CONTROL_OBJECT_ID

try:  # an engine without the module attaches no context: every write is refused
    from ai.common.tool_context import current_tool_call as _engine_current_tool_call
except ImportError:  # pragma: no cover - exercised by loading a copy without the module
    _engine_current_tool_call = None

#: Reads the engine's context for the running call (None on an engine without it).
_current_tool_call = _engine_current_tool_call

#: The tools that write and therefore run the gate.
WRITE_TOOLS = ('remove_document', 'delete', 'upsert')

#: Caller kinds allowed to write through DAP.
WRITE_CALLER_AUTH = ('account', 'task')

#: The source type allowed to write through DAP.
WRITE_SOURCE_TYPE = 'tools'

_VERB = {'remove_document': 'remove documents', 'delete': 'remove documents', 'upsert': 'add documents'}
_DISABLED = {
    'remove_document': 'Removing documents is turned off on this store node (allow_writes).',
    'delete': 'Removing documents is turned off on this store node (allow_writes).',
    'upsert': 'Adding documents through tool calls is turned off on this store node (allow_writes).',
}
_RESERVED = {
    'remove_document': "'schema' is the collection's control record and cannot be removed.",
    'delete': "'schema' is the collection's control record and cannot be removed.",
    'upsert': "'schema' is the collection's control record and cannot be written.",
}


@dataclass(frozen=True)
class GateContext:
    """The parts of a call context the gate reads."""

    origin: str
    source_type: Optional[str]
    targeted: bool
    caller: Mapping[str, Any]


@dataclass(frozen=True)
class GateDecision:
    """An allowed write: who asked, for the audit block."""

    origin: str
    #: ``{'auth', 'userId', 'teamId'}``; no other caller detail is kept.
    caller: Dict[str, Any]


def _read(ctx: Any) -> Optional[GateContext]:
    """Coerce a ``ToolCallContext`` (or its ``__dict__``) to :class:`GateContext`; None when unreadable."""
    if ctx is None:
        return None
    if isinstance(ctx, Mapping):
        get = ctx.get
    else:

        def get(name: str, default: Any = None) -> Any:
            return getattr(ctx, name, default)

    origin = get('origin')
    caller = get('caller')
    if origin not in ('dap', 'agent') or not isinstance(caller, Mapping):
        return None
    source_type = get('source_type')
    return GateContext(
        origin=origin,
        source_type=source_type if isinstance(source_type, str) else None,
        targeted=get('targeted') is True,
        caller=caller,
    )


def current_context() -> Any:
    """Return the engine's context for the running tool call, or None (no context, or the reader failed)."""
    reader = _current_tool_call
    if reader is None:
        return None
    try:
        return reader()
    except Exception:
        return None


_UNSET = object()


def check_write(
    tool: str,
    *,
    object_ids: Sequence[str],
    allow_writes: bool,
    agent_writes: bool,
    supplies_embedding: bool = False,
    context: Any = _UNSET,
) -> GateDecision:
    """Decide whether ``tool`` may write ``object_ids``; raise a refusal when it may not.

    :param tool: ``'remove_document'``, ``'delete'`` or ``'upsert'``.
    :param object_ids: Every objectId the call would write or remove.
    :param allow_writes: The node's ``allow_writes`` switch (DAP calls).
    :param agent_writes: The node's ``agent_writes`` switch (agent calls).
    :param supplies_embedding: True when an ``upsert`` carries caller-supplied embeddings.
    :param context: The call context; read from the engine when left out.
    :raises ToolRefusal: With the code of the first row of the gate that refuses.
    """
    if any(str(oid).strip() == CONTROL_OBJECT_ID for oid in object_ids):
        raise ToolRefusal('RESERVED_ID', _RESERVED.get(tool, _RESERVED['upsert']))

    ctx = _read(current_context() if context is _UNSET else context)
    if ctx is None:
        raise ToolRefusal(
            'WRITES_UNKNOWN_CALLER', 'The engine did not identify this request, so the store refused the write.'
        )

    if ctx.origin == 'agent':
        if not agent_writes:
            raise ToolRefusal('WRITES_AGENT', 'Writes from agents are turned off on this store node (agent_writes).')
        return GateDecision(origin='agent', caller={'auth': 'agent', 'userId': None, 'teamId': None})

    if not allow_writes:
        raise ToolRefusal('WRITES_DISABLED', _DISABLED.get(tool, _DISABLED['upsert']))
    if ctx.source_type != WRITE_SOURCE_TYPE:
        raise ToolRefusal('WRITES_SOURCE', f'Only a Tools source may {_VERB.get(tool, "write documents")}.')
    if ctx.caller.get('auth') not in WRITE_CALLER_AUTH:
        raise ToolRefusal('WRITES_PUBLIC', 'The store refused this request.')
    if not ctx.targeted:
        raise ToolRefusal('WRITES_BROADCAST', 'The store refused this request: name the node the write is for.')
    if supplies_embedding:
        raise ToolRefusal(
            'INVALID_INPUT',
            'Tool calls cannot supply embeddings; leave out "embedding" and "embedding_model" and the store computes them.',
        )
    return GateDecision(
        origin='dap',
        caller={'auth': ctx.caller.get('auth'), 'userId': ctx.caller.get('userId'), 'teamId': ctx.caller.get('teamId')},
    )


__all__ = ['GateDecision', 'WRITE_TOOLS', 'check_write', 'current_context']
