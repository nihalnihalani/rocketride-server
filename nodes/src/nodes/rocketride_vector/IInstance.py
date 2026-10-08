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

# ------------------------------------------------------------------------------
# This class controls the data for each thread of the task.
#
# The lane handlers (questions search, documents write, render) and the store
# tools come from StoreInstanceBase, as on every vector store node.
#
# The table is shared by every pipeline of the organization, so the two tools
# that change it (upsert, delete) first pass a local check that fails closed:
# the reserved control-record id, a call without the engine's call context,
# and the two write switches are refused here, in the same order and with the
# same codes as the store write gate, before the call reaches the base class
# (and, where it exists, that gate).
# ------------------------------------------------------------------------------
import functools
from typing import Any, Dict, Iterable, Optional

from .IGlobal import IGlobal
from ai.common.config import Config
from ai.common.store import StoreInstanceBase
from ai.common.store.document_store import _normalize_vectordb_tool_input
from ai.common.store.vx_defaults import VECTOR_AGENT_WRITES_DEFAULT, VECTOR_ALLOW_WRITES_DEFAULT
from ai.common.utils.config_utils import parse_bool

try:
    from ai.common.tool_context import current_tool_call
except ImportError:  # an engine without call contexts: every write is from an unknown caller

    def current_tool_call():
        return None


#: objectId of the collection's control record; no tool may change it.
RESERVED_OBJECT_ID = 'schema'

_REFUSALS = {
    'RESERVED_ID': "'schema' is the collection's control record and cannot be changed.",
    'WRITES_UNKNOWN_CALLER': 'The engine did not identify this request, so the store refused the write.',
    'WRITES_AGENT': 'Writes from agents are turned off on this store node (agent_writes).',
    'WRITES_DISABLED': 'Writes from tool calls are turned off on this store node (allow_writes).',
}


class IInstance(StoreInstanceBase):
    IGlobal: IGlobal

    @functools.wraps(StoreInstanceBase.upsert)
    def upsert(self, args):
        """Add or update documents, once the write check allows the call."""
        documents = _normalize_vectordb_tool_input(args).get('documents')
        object_ids = (
            [d.get('object_id') for d in documents if isinstance(d, dict)] if isinstance(documents, list) else []
        )
        refusal = self._write_refusal(object_ids)
        return refusal if refusal is not None else super().upsert(args)

    @functools.wraps(StoreInstanceBase.delete)
    def delete(self, args):
        """Delete documents by object ID, once the write check allows the call."""
        object_ids = _normalize_vectordb_tool_input(args).get('object_ids')
        refusal = self._write_refusal(object_ids if isinstance(object_ids, list) else [])
        return refusal if refusal is not None else super().delete(args)

    def _write_refusal(self, object_ids: Iterable[Any]) -> Optional[Dict[str, Any]]:
        """The refusal envelope for a write tool call, or None when the call may go on."""
        if any(str(o).strip() == RESERVED_OBJECT_ID for o in object_ids if o is not None):
            return _refuse('RESERVED_ID')
        ctx = current_tool_call()
        if ctx is None:
            return _refuse('WRITES_UNKNOWN_CALLER')
        origin = getattr(ctx, 'origin', None)
        if origin == 'agent' and not self._switch('agent_writes', VECTOR_AGENT_WRITES_DEFAULT):
            return _refuse('WRITES_AGENT')
        if origin != 'agent' and not self._switch('allow_writes', VECTOR_ALLOW_WRITES_DEFAULT):
            return _refuse('WRITES_DISABLED')
        return None

    def _switch(self, name: str, default: bool) -> bool:
        """A write switch of this node, from its merged configuration."""
        glb = self.IGlobal
        config = Config.getNodeConfig(glb.glb.logicalType, glb.getConnConfig())
        return parse_bool(config.get(name) if hasattr(config, 'get') else None, default)


def _refuse(code: str) -> Dict[str, Any]:
    return {'success': False, 'code': code, 'error': _REFUSALS[code]}
