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

"""Who is calling a node tool: the call context the engine attaches to every tool invoke.

A node tool that changes data (the vector store write tools) needs to know where
a call came from before it acts. The engine, never the client, sets that context:

1. The DAP tool path stamps the ``IInvokeTool.Invoke`` param it builds with
   ``param.__tool_context__`` (:data:`TOOL_CONTEXT_FIELD`): origin ``'dap'``, the
   calling task's source type, whether the call named a node, and the caller as
   the server sees it. Nothing inside the tool ``input`` is ever read as context.
2. The agent host stamps the params it builds with origin ``'agent'``.
3. ``IInstanceBase._dispatch_tool`` reads the field and runs the tool method
   inside :func:`tool_call`, so the method can read :func:`current_tool_call`.

A tool that finds no context (an engine without this module, or a dispatcher
that did not stamp the call) must treat the caller as unknown and refuse writes.

**Status: interface only.** :func:`current_tool_call` always returns ``None``
and :func:`tool_call` does not record its context yet; the engine wiring
(stamping and the dispatcher) lands separately. Until then every write that
depends on a context is refused, which is the fail-closed behaviour.

See ``docs/development/nodes/vector-tool-contract.md`` section 6.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

#: Name of the extra field on the ``IInvokeTool`` param that carries the context
#: (the invoke param model allows extra fields).
TOOL_CONTEXT_FIELD = '__tool_context__'

#: ``ToolCallContext.origin`` values.
ORIGINS: Tuple[str, ...] = ('dap', 'agent')

#: ``ToolCallContext.caller['auth']`` values.
CALLER_AUTH_KINDS: Tuple[str, ...] = ('public', 'task', 'account', 'agent', 'unknown')


@dataclass(frozen=True)
class ToolCallContext:
    """Where one tool call came from, as the engine established it.

    :param origin: ``'dap'`` (an external tool call through the engine's DAP) or ``'agent'``
        (a tool call made by an agent node inside the pipeline).
    :param source_type: The provider of the calling task's source component (``'tools'``,
        ``'chat'``, ``'dropper'``, ...); None when unknown (always None for agent calls).
    :param targeted: True when the call named the target node explicitly.
    :param caller: ``{'auth': one of CALLER_AUTH_KINDS, 'userId', 'teamId', 'orgId'}`` as the
        server sees the caller. Ids may be absent or None.
    """

    origin: str
    source_type: Optional[str]
    targeted: bool
    caller: Dict[str, Any]


def current_tool_call() -> Optional[ToolCallContext]:
    """Return the context of the tool call running on this thread, or None when there is none.

    Interface stub: always returns None until the engine wiring lands, so every
    caller that needs a context fails closed.
    """
    return None


@contextmanager
def tool_call(ctx: ToolCallContext) -> Iterator[ToolCallContext]:
    """Run the body as the tool call described by ``ctx``.

    The dispatcher wraps each tool method call in this. Interface stub: the
    context is validated and yielded but not yet recorded, so
    :func:`current_tool_call` still returns None inside the body.

    :param ctx: The call context; must be a :class:`ToolCallContext`.
    :raises TypeError: When ``ctx`` is not a :class:`ToolCallContext`.
    """
    if not isinstance(ctx, ToolCallContext):
        raise TypeError(f'tool_call expects a ToolCallContext, got {type(ctx).__name__}')
    yield ctx


__all__ = [
    'CALLER_AUTH_KINDS',
    'ORIGINS',
    'TOOL_CONTEXT_FIELD',
    'ToolCallContext',
    'current_tool_call',
    'tool_call',
]
