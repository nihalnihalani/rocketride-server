# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Unit tests for the VectorStoreToolMixin (packages/ai/src/ai/common/store/document_store.py).

These tests run the mixin on the engine's own modules (``rocketlib``,
``ai.common.schema``, ``ai.common.store``) with a fake store and a fake IGlobal,
so no server or database is needed. They cover:

* ``_normalize_vectordb_tool_input`` — dict / JSON / pydantic / nested /
  malformed / security-context stripping.
* Tool name collection — bare method names (no server-name prefix).
* Dispatch — ``search``, ``upsert``, ``delete`` call through to a fake store
  and propagate errors when the store is missing.
* Semantic search — when ``IGlobal.embed_query`` is present the mixin
  populates ``question.embedding``; when absent returns an error envelope.
* Auto-embed on upsert — mixin computes embeddings via IGlobal.embed_query
  and sets both Doc.embedding and Doc.embedding_model before addChunks.
* The Vector Explorer tools (``dialect``, ``stats``, ``documents``, ``chunks``,
  ``vectors``, ``sample``, ``project``, ``neighbors``, ``remove_document``) and
  the additive answers of the legacy tools, over the in-memory drivers of
  ``test_vector_hooks``: each tool's success answer and every code it can return.

Write tools run the gate, which reads the engine's call context; tests set it
with the ``context`` fixture (``agent()`` / ``dap()``).
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pytest
from rocketlib import IInstanceBase

from ai.common.schema import Doc, DocMetadata
from ai.common.store import VectorStoreToolMixin, vx_tools, vx_write_gate
from ai.common.store import document_store as _store_module
from ai.common.store.errors import StoreUnsupported
from ai.common.store.vx_defaults import VECTOR_TOOL_LIMITS

from .test_vector_hooks import (
    MODEL,
    CountingStore,
    ExactListingStore,
    MemoryStore,
    NativeStratifiedStore,
    VectorMemoryStore,
    corpus,
    make_doc,
)
from .test_vector_write_gate import agent, dap

_normalize_vectordb_tool_input = _store_module._normalize_vectordb_tool_input

_WARNINGS: List[str] = []


@pytest.fixture(autouse=True)
def _capture_warnings(monkeypatch):
    """Collect what the store module logs with ``warning()``."""
    _WARNINGS.clear()
    monkeypatch.setattr(_store_module, 'warning', lambda msg: _WARNINGS.append(str(msg)))
    monkeypatch.setattr(vx_tools, 'warning', lambda msg: _WARNINGS.append(str(msg)))
    yield


@pytest.fixture
def context(monkeypatch):
    """Set the call context the write gate reads; None until a test sets one."""
    holder: Dict[str, Any] = {'ctx': None}
    monkeypatch.setattr(vx_write_gate, '_current_tool_call', lambda: holder['ctx'])

    def set_context(ctx: Any) -> None:
        holder['ctx'] = ctx

    return set_context


@pytest.fixture
def agent_context(context):
    """An agent call (the legacy write path), allowed with the default switches."""
    context(agent())


def _meta(**kwargs: Any) -> DocMetadata:
    kwargs.setdefault('chunkId', 0)
    return DocMetadata(**kwargs)


def _doc(page_content: str = '', metadata: Optional[DocMetadata] = None, score: float = 0.0) -> Doc:
    doc = Doc(page_content=page_content, metadata=metadata)
    doc.score = score
    return doc


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeStore:
    """Captures calls to searchSemantic/searchKeyword/addChunks/remove."""

    def __init__(self, semantic_docs: Optional[List[Doc]] = None, keyword_docs: Optional[List[Doc]] = None) -> None:
        """Seed the fake store with optional pre-canned result lists."""
        self.semantic_docs = semantic_docs if semantic_docs is not None else []
        self.keyword_docs = keyword_docs if keyword_docs is not None else []
        self.semantic_calls: List[tuple] = []
        self.keyword_calls: List[tuple] = []
        self.added_chunks: List[list] = []
        self.removed_ids: List[list] = []
        self.raise_semantic: Optional[Exception] = None

    def searchSemantic(self, question: Any, doc_filter: Any) -> List[Doc]:
        self.semantic_calls.append((question, doc_filter))
        if self.raise_semantic is not None:
            raise self.raise_semantic
        return self.semantic_docs

    def searchKeyword(self, question: Any, doc_filter: Any) -> List[Doc]:
        self.keyword_calls.append((question, doc_filter))
        return self.keyword_docs

    def addChunks(self, chunks: list) -> None:
        self.added_chunks.append(chunks)

    def remove(self, object_ids: list) -> None:
        self.removed_ids.append(object_ids)


class FakeGlb:
    def __init__(self, logical_type: str = 'pinecone') -> None:
        """Store the logical type used for fallback namespacing."""
        self.logicalType = logical_type


class FakeIGlobal:
    def __init__(
        self,
        store: Optional[FakeStore] = None,
        server_name: Optional[str] = None,
        embed_query: Optional[Callable] = None,
        logical_type: str = 'pinecone',
        embed_model_name: Optional[str] = None,
    ) -> None:
        """Assemble a fake IGlobal with optional embedder and server name."""
        self.store = store
        if server_name is not None:
            self.serverName = server_name
        self.glb = FakeGlb(logical_type)
        if embed_query is not None:
            self.embed_query = embed_query
        if embed_model_name is not None:
            self.embed_model_name = embed_model_name


class FakeIInstance(VectorStoreToolMixin, IInstanceBase):
    def __init__(self, iglobal: FakeIGlobal) -> None:
        """Attach the fake IGlobal so the mixin sees the configured store."""
        self.IGlobal = iglobal


def _fresh_warnings() -> None:
    _WARNINGS.clear()


# ---------------------------------------------------------------------------
# _normalize_vectordb_tool_input
# ---------------------------------------------------------------------------


def test_normalize_none_returns_empty_dict() -> None:
    assert _normalize_vectordb_tool_input(None) == {}


def test_normalize_plain_dict_passes_through() -> None:
    result = _normalize_vectordb_tool_input({'query': 'hello', 'top_k': 5})
    assert result == {'query': 'hello', 'top_k': 5}


def test_normalize_json_string() -> None:
    result = _normalize_vectordb_tool_input('{"query": "hello"}')
    assert result == {'query': 'hello'}


def test_normalize_malformed_json_returns_empty() -> None:
    _fresh_warnings()
    result = _normalize_vectordb_tool_input('{not json')
    assert result == {}
    assert any('malformed JSON' in w for w in _WARNINGS)


def test_normalize_pydantic_v2_model() -> None:
    class FakeModel:
        def model_dump(self) -> Dict[str, Any]:
            return {'query': 'hello', 'top_k': 3}

    result = _normalize_vectordb_tool_input(FakeModel())
    assert result == {'query': 'hello', 'top_k': 3}


def test_normalize_pydantic_v1_model() -> None:
    class FakeV1:
        def dict(self) -> Dict[str, Any]:
            return {'query': 'legacy'}

    result = _normalize_vectordb_tool_input(FakeV1())
    assert result == {'query': 'legacy'}


def test_normalize_nested_input_wrapper_dict() -> None:
    result = _normalize_vectordb_tool_input({'input': {'query': 'hi'}, 'top_k': 7})
    assert result == {'query': 'hi', 'top_k': 7}


def test_normalize_nested_input_wrapper_json_string() -> None:
    result = _normalize_vectordb_tool_input({'input': '{"query": "hi"}'})
    assert result == {'query': 'hi'}


def test_normalize_strips_security_context() -> None:
    result = _normalize_vectordb_tool_input({'query': 'x', 'security_context': {'user': 'root'}})
    assert 'security_context' not in result
    assert result == {'query': 'x'}


def test_normalize_non_dict_json_returns_empty() -> None:
    _fresh_warnings()
    result = _normalize_vectordb_tool_input('"just a string"')
    assert result == {}


# ---------------------------------------------------------------------------
# Tool collection (bare names — agent framework adds node-ID prefix)
# ---------------------------------------------------------------------------

# Expected bare tool names from VectorStoreToolMixin
_LEGACY_TOOLS = {'search', 'upsert', 'delete', 'objdir', 'stats', 'get'}
_EXPLORER_TOOLS = {'dialect', 'documents', 'chunks', 'vectors', 'sample', 'project', 'neighbors', 'remove_document'}
_EXPECTED_TOOLS = _LEGACY_TOOLS | _EXPLORER_TOOLS


def test_collect_tool_methods_returns_bare_names() -> None:
    """Tools must use bare method names; the agent framework adds the node-ID prefix."""
    instance = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='myvdb'))
    methods = instance._collect_tool_methods()

    assert set(methods.keys()) == _EXPECTED_TOOLS
    # Each value is a callable bound to the fake instance
    for bound in methods.values():
        assert callable(bound)


def test_collect_tool_methods_bare_names_regardless_of_provider() -> None:
    """Bare names must be identical regardless of the provider / serverName."""
    instance = FakeIInstance(FakeIGlobal(store=FakeStore(), logical_type='chroma'))
    methods = instance._collect_tool_methods()
    assert set(methods.keys()) == _EXPECTED_TOOLS


def test_collect_tool_methods_bare_names_when_no_globals() -> None:
    class Orphan(VectorStoreToolMixin, IInstanceBase):
        pass

    orphan = object.__new__(Orphan)
    orphan.IGlobal = None
    methods = orphan._collect_tool_methods()
    assert set(methods.keys()) == _EXPECTED_TOOLS


def test_two_instances_share_bare_names() -> None:
    """Two vector store instances expose the same bare tool names.

    The agent framework disambiguates via node-ID prefixes at discovery time.
    """
    a = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='primary', logical_type='pinecone'))
    b = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='secondary', logical_type='pinecone'))

    names_a = set(a._collect_tool_methods().keys())
    names_b = set(b._collect_tool_methods().keys())
    assert names_a == names_b == _EXPECTED_TOOLS


# ---------------------------------------------------------------------------
# Tool schema contract (#1092 — advertised keys must match what dispatch reads)
# ---------------------------------------------------------------------------


def test_search_filter_schema_enumerates_only_honored_keys() -> None:
    """The filter schema must reject keys search() does not read (#1092)."""
    schema = VectorStoreToolMixin.search.__tool_meta__['input_schema']
    filter_schema = schema['properties']['filter']

    assert filter_schema['additionalProperties'] is False
    assert set(filter_schema['properties']) == {'objectId', 'nodeId', 'parent'}


def test_upsert_metadata_schema_enumerates_only_honored_keys() -> None:
    """The per-document metadata schema must reject keys upsert() does not store (#1092)."""
    schema = VectorStoreToolMixin.upsert.__tool_meta__['input_schema']
    meta_schema = schema['properties']['documents']['items']['properties']['metadata']

    assert meta_schema['additionalProperties'] is False
    assert set(meta_schema['properties']) == {'nodeId', 'parent', 'chunkId'}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def test_search_returns_error_envelope_when_no_embedder() -> None:
    """No embed_query on IGlobal → search must return a failure envelope, not fall back to keyword."""
    _fresh_warnings()
    store = FakeStore(keyword_docs=[_doc(page_content='cat', score=0.9, metadata=_meta(objectId='d1'))])
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    result = instance.search({'query': 'cat'})

    assert result.get('success') is False
    assert 'error' in result
    assert 'embed' in result['error'].lower() or 'embedding' in result['error'].lower()
    # Must NOT have called keyword search — this is a hard failure, not a silent fallback
    assert store.keyword_calls == []
    assert store.semantic_calls == []


def test_search_warns_only_once_across_calls() -> None:
    """The no-embedder warning (if any) must fire at most once across repeated calls."""
    _fresh_warnings()
    store = FakeStore()
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    instance.search({'query': 'a'})
    instance.search({'query': 'b'})
    instance.search({'query': 'c'})

    # At most one warning mentioning the missing embedder
    embedder_warnings = [w for w in _WARNINGS if 'embed' in w.lower()]
    assert len(embedder_warnings) <= 1


def test_search_uses_semantic_when_embed_query_present() -> None:
    embed_calls: List[str] = []

    def embed_query(text: str) -> list:
        embed_calls.append(text)
        return [0.1, 0.2, 0.3]

    store = FakeStore(semantic_docs=[_doc(page_content='dog', score=0.8, metadata=_meta(objectId='d2'))])
    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='test-model')
    )

    result = instance.search({'query': 'dog'})

    assert embed_calls == ['dog']
    assert len(store.semantic_calls) == 1
    assert store.keyword_calls == []
    # The question passed to searchSemantic must have embedding populated
    question, _ = store.semantic_calls[0]
    assert question.embedding == [0.1, 0.2, 0.3]
    assert question.embedding_model == 'test-model'
    assert result['total'] == 1


def test_search_uses_iglobal_embed_query_when_bound() -> None:
    """embed_query result AND embed_model_name must flow into QuestionText before searchSemantic."""
    embedded_vector = [0.5, 0.6, 0.7]
    embed_calls: List[str] = []

    def embed_query(text: str) -> list:
        embed_calls.append(text)
        return embedded_vector

    store = FakeStore(semantic_docs=[_doc(page_content='result', score=0.9, metadata=_meta(objectId='r1'))])
    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='ada-002')
    )

    result = instance.search({'query': 'find me'})

    assert result.get('success') is not False, f'Expected success but got: {result}'
    assert len(store.semantic_calls) == 1
    question, _ = store.semantic_calls[0]
    assert question.embedding == embedded_vector
    assert question.embedding_model == 'ada-002'
    assert embed_calls == ['find me']


def test_search_empty_query_returns_error_envelope() -> None:
    instance = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='vdb'))
    result = instance.search({'query': ''})
    assert result.get('success') is False
    assert 'error' in result
    assert 'non-empty' in result['error'] or 'query' in result['error'].lower()


def test_search_falls_back_to_keyword_on_semantic_exception() -> None:
    """When embed_query IS bound but searchSemantic raises, fall back to keyword search."""
    _fresh_warnings()
    store = FakeStore(keyword_docs=[_doc(page_content='kw', score=0.5, metadata=_meta(objectId='d1'))])
    store.raise_semantic = RuntimeError('index missing')
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb', embed_query=lambda _t: [0.0, 0.1]))

    result = instance.search({'query': 'hello'})

    assert len(store.semantic_calls) == 1
    assert len(store.keyword_calls) == 1
    assert result['total'] == 1
    assert any('semantic search failed' in w for w in _WARNINGS)


def test_search_reports_a_missing_store_as_a_store_error() -> None:
    instance = FakeIInstance(FakeIGlobal(store=None, server_name='vdb'))
    result = instance.search({'query': 'x'})
    assert result['success'] is False
    assert result['code'] == 'STORE_ERROR'
    assert 'store not initialized' in result['error']


def test_upsert_adds_chunks(agent_context) -> None:
    store = FakeStore()

    def embed_query(text: str) -> list:
        return [0.1, 0.2, 0.3]

    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='test-model')
    )

    result = instance.upsert(
        {
            'documents': [
                {'content': 'doc one text', 'object_id': 'obj-1'},
                {'content': 'doc two', 'object_id': 'obj-2', 'metadata': {'nodeId': 'foo', 'parent': '/p'}},
            ]
        }
    )

    assert (result['success'], result['count'], result['skipped']) == (True, 2, 0)
    assert len(store.added_chunks) == 1
    chunks = store.added_chunks[0]
    assert len(chunks) == 2
    assert chunks[0].metadata.objectId == 'obj-1'
    assert chunks[1].metadata.nodeId == 'foo'
    assert chunks[1].metadata.parent == '/p'


def test_upsert_skips_invalid_entries(agent_context) -> None:
    store = FakeStore()

    def embed_query(text: str) -> list:
        return [0.1, 0.2, 0.3]

    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='test-model')
    )

    result = instance.upsert(
        {
            'documents': [
                {'content': 'valid', 'object_id': 'obj-1'},
                {'content': '', 'object_id': 'obj-2'},  # missing content
                {'content': 'text', 'object_id': ''},  # missing id
                'not a dict',
            ]
        }
    )
    assert result['success'] is True
    assert result['count'] == 1
    assert result['skipped'] == 3


def test_upsert_auto_embeds_when_iglobal_has_embedder(agent_context) -> None:
    """When IGlobal.embed_query is bound and no per-doc embedding is supplied,
    the mixin must compute and set Doc.embedding + Doc.embedding_model before addChunks.
    """
    store = FakeStore()
    embed_calls: List[str] = []

    def embed_query(text: str) -> list:
        embed_calls.append(text)
        return [0.9, 0.8, 0.7]

    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='my-model')
    )

    result = instance.upsert({'documents': [{'content': 'hello world', 'object_id': 'doc-1'}]})

    assert result.get('success') is True
    assert len(store.added_chunks) == 1
    chunks = store.added_chunks[0]
    assert len(chunks) == 1
    doc = chunks[0]
    assert doc.embedding == [0.9, 0.8, 0.7], f'Expected embedding to be set, got {doc.embedding}'
    assert doc.embedding_model == 'my-model', f'Expected embedding_model to be set, got {doc.embedding_model}'
    assert embed_calls == ['hello world']


def test_upsert_uses_caller_supplied_embedding_and_model(agent_context) -> None:
    """When the caller passes embedding + embedding_model per-doc, those values must be
    used verbatim and embed_query must NOT be called.
    """
    store = FakeStore()
    embed_calls: List[str] = []

    def embed_query(text: str) -> list:
        embed_calls.append(text)
        return [0.0]  # should never be reached

    caller_vector = [1.0, 2.0, 3.0]
    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='iglobal-model')
    )

    result = instance.upsert(
        {
            'documents': [
                {
                    'content': 'pre-embedded text',
                    'object_id': 'doc-2',
                    'embedding': caller_vector,
                    'embedding_model': 'caller-model',
                }
            ]
        }
    )

    assert result.get('success') is True
    assert embed_calls == [], 'embed_query must not be called when caller supplies embedding'
    chunks = store.added_chunks[0]
    doc = chunks[0]
    assert doc.embedding == caller_vector
    assert doc.embedding_model == 'caller-model'


def test_upsert_returns_error_envelope_when_no_embedder_and_no_caller_vector(agent_context) -> None:
    """No IGlobal.embed_query and no per-doc embedding → error envelope, no addChunks call."""
    store = FakeStore()
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    result = instance.upsert({'documents': [{'content': 'some text', 'object_id': 'doc-3'}]})

    assert result.get('success') is False
    assert 'error' in result
    assert 'embed' in result['error'].lower() or 'embedding' in result['error'].lower()
    assert store.added_chunks == [], 'addChunks must not be called when embedder is missing'


def test_upsert_returns_error_envelope_when_caller_supplies_only_embedding_no_model(agent_context) -> None:
    """Caller provides embedding but omits embedding_model → error envelope."""
    store = FakeStore()
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    result = instance.upsert(
        {
            'documents': [
                {
                    'content': 'text',
                    'object_id': 'doc-4',
                    'embedding': [0.1, 0.2],
                    # intentionally no 'embedding_model'
                }
            ]
        }
    )

    assert result.get('success') is False
    assert 'error' in result
    assert store.added_chunks == []


def test_upsert_requires_documents(agent_context) -> None:
    instance = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='vdb'))
    result = instance.upsert({'documents': []})
    # Must be an error envelope (success=False) rather than raising ValueError
    assert result.get('success') is False
    assert 'error' in result


def test_delete_calls_store_remove(agent_context) -> None:
    store = MemoryStore().seed(corpus({'a': [0], 'b': [0], 'c': [0]}))
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    result = instance.delete({'object_ids': ['a', 'b', 'c']})

    assert (result['success'], result['deleted_count']) == (True, 3)
    assert [call for call in store.calls if call[0] == 'remove'] == [('remove', ['a', 'b', 'c'])]


def test_delete_strips_whitespace_and_drops_empty(agent_context) -> None:
    store = MemoryStore().seed(corpus({'id-1': [0], 'id-2': [0]}))
    instance = FakeIInstance(FakeIGlobal(store=store, server_name='vdb'))

    result = instance.delete({'object_ids': ['  id-1 ', '', '   ', 'id-2']})
    assert (result['success'], result['deleted_count']) == (True, 2)
    assert [call for call in store.calls if call[0] == 'remove'] == [('remove', ['id-1', 'id-2'])]


def test_delete_requires_object_ids() -> None:
    instance = FakeIInstance(FakeIGlobal(store=FakeStore(), server_name='vdb'))
    result = instance.delete({'object_ids': []})
    # Must be an error envelope (success=False) rather than raising ValueError
    assert result.get('success') is False
    assert 'error' in result


def test_upsert_returns_envelope_on_store_addchunks_exception(agent_context) -> None:
    """If addChunks raises (e.g. model-mismatch), upsert must catch it and return an error envelope."""

    class RaisingStore(FakeStore):
        def addChunks(self, chunks: list) -> None:
            raise RuntimeError('model mismatch: collection uses ada-002 but doc encoded with text-3')

    store = RaisingStore()

    def embed_query(text: str) -> list:
        return [0.1, 0.2]

    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='vdb', embed_query=embed_query, embed_model_name='text-3')
    )

    result = instance.upsert({'documents': [{'content': 'some text', 'object_id': 'doc-5'}]})

    assert result.get('success') is False
    assert 'error' in result


def test_dispatch_via_bare_name() -> None:
    """End-to-end: _collect_tool_methods -> lookup -> invoke via bare key."""
    embed_calls: List[str] = []

    def embed_query(text: str) -> list:
        embed_calls.append(text)
        return [1.0, 0.0]

    store = FakeStore(semantic_docs=[_doc(page_content='hit', score=1.0, metadata=_meta(objectId='o1'))])
    instance = FakeIInstance(
        FakeIGlobal(store=store, server_name='pinecone', embed_query=embed_query, embed_model_name='test')
    )

    methods = instance._collect_tool_methods()
    assert 'search' in methods

    # Simulate engine dispatch: methods[tool_name](input_obj)
    result = methods['search']({'query': 'hit'})
    assert result['total'] == 1
    assert result['results'][0]['content'] == 'hit'


def test_normalize_handles_nested_input_with_security_context() -> None:
    result = _normalize_vectordb_tool_input({'input': {'query': 'x', 'security_context': {'user': 'root'}}})
    assert result == {'query': 'x'}


# ===========================================================================
# Explorer tools over the in-memory drivers
# ===========================================================================


class Node(VectorStoreToolMixin, IInstanceBase):
    """A store node instance as the engine dispatches tools to it."""


def node(
    store: Any,
    *,
    allow_writes: Optional[bool] = None,
    agent_writes: Optional[bool] = None,
    logical_type: str = 'postgres',
    node_id: str = 'store_1',
    embed_query: Optional[Callable] = None,
    embed_model_name: Optional[str] = None,
) -> Node:
    inst = object.__new__(Node)
    glb = SimpleNamespace(store=store, glb=SimpleNamespace(logicalType=logical_type), serverName='vdb')
    if allow_writes is not None:
        glb.allow_writes = allow_writes
    if agent_writes is not None:
        glb.agent_writes = agent_writes
    if embed_query is not None:
        glb.embed_query = embed_query
        glb.embed_model_name = embed_model_name
    inst.IGlobal = glb
    inst.instance = SimpleNamespace(pipeType={'id': node_id})
    return inst


def _unit(v: List[float]) -> List[float]:
    a = np.asarray(v, dtype=np.float64)
    return (a / np.linalg.norm(a)).tolist()


def clustered(
    store_cls=ExactListingStore,
    *,
    docs: int = 6,
    chunks: int = 5,
    dim: int = 8,
    text_chars: int = 0,
    spread: float = 0.6,
    **kw,
):
    """A store with ``docs`` documents of ``chunks`` chunks scattered (``spread``) around per-document directions."""
    rng = np.random.default_rng(1234)
    kw.setdefault('provider', 'postgres')
    store = store_cls(**kw)
    batch = []
    for d in range(docs):
        centre = rng.normal(size=dim)
        for c in range(chunks):
            vec = _unit((centre + spread * rng.normal(size=dim)).tolist())
            text = (f'doc{d:02d} chunk {c} ' + 'lorem ipsum dolor sit amet ' * (text_chars // 27 + 1))[
                : max(text_chars, 20)
            ]
            batch.append(make_doc(f'doc{d:02d}', c, path=f'C:/demo/folder{d % 3}/doc{d:02d}.md', vector=vec, text=text))
    store.seed(batch)
    return store


def _no_vectors_anywhere(value: Any, dimension: int) -> bool:
    """True when no list of ``dimension`` floats appears in ``value`` (raw vectors stay on the node)."""
    if isinstance(value, dict):
        return all(_no_vectors_anywhere(v, dimension) for v in value.values())
    if isinstance(value, list):
        if len(value) == dimension and value and all(isinstance(x, float) for x in value):
            return False
        return all(_no_vectors_anywhere(v, dimension) for v in value)
    return True


# ---------------------------------------------------------------------------
# dialect
# ---------------------------------------------------------------------------


def test_dialect_describes_the_store():
    store = clustered(NativeStratifiedStore)
    answer = node(store).dialect({})
    assert answer['success'] is True
    assert (answer['dialect'], answer['contract'], answer['provider'], answer['backend']) == (
        'vector',
        'vector/1',
        'postgres',
        'pgvector',
    )
    assert (answer['collection'], answer['metric'], answer['model'], answer['dimension']) == (
        'vx_test_docs',
        'cosine',
        MODEL,
        8,
    )
    assert answer['score'] == {'formula': 'unknown', 'higher_is_better': True, 'floor': 0.2, 'threshold': 0.3}
    assert answer['write_tools'] == ['remove_document', 'delete', 'upsert']
    assert answer['writes_scope'] == 'tools_source'
    assert answer['health'] == {
        'collection_exists': True,
        'control_record': True,
        'model_mismatch': None,
        'meta_column': None,
    }
    assert answer['limits'] == VECTOR_TOOL_LIMITS


def test_dialect_capabilities_follow_the_driver():
    caps = node(clustered(NativeStratifiedStore)).dialect({})['capabilities']
    assert caps['count_documents'] and caps['vectors'] and caps['sample'] and caps['sample_light']
    assert caps['sample_stratified_native'] and caps['documents_distinct'] and caps['documents_sorted']
    assert caps['search_keyword'] and caps['remove_count'] and caps['project'] and caps['neighbors']
    assert caps['knn_native'] is False and caps['soft_delete'] is False and caps['search_vector'] is True
    assert caps['projection'] == ['pca']
    bare = node(MemoryStore().seed(corpus({'a': [0]}))).dialect({})['capabilities']
    assert bare['vectors'] is False and bare['sample'] is False and bare['count_documents'] is False
    assert bare['documents'] is True and bare['chunks'] is True and bare['remove_count'] is False


def test_dialect_reports_the_write_switches():
    store = clustered()
    assert node(store).dialect({})['allow_writes'] is False
    answer = node(store, allow_writes=True, agent_writes=False).dialect({})
    assert (answer['allow_writes'], answer['agent_writes']) == (True, False)


def test_dialect_on_a_missing_collection_is_a_success_with_nulls():
    answer = node(MemoryStore()).dialect({})
    assert answer['success'] is True
    assert answer['health'] == {
        'collection_exists': False,
        'control_record': None,
        'model_mismatch': None,
        'meta_column': None,
    }
    assert (answer['metric'], answer['model'], answer['dimension'], answer['index']) == (None, None, None, None)


def test_dialect_reports_a_missing_control_record():
    store = clustered()
    del store.rows[('schema', 0)]
    assert node(store).dialect({})['health']['control_record'] is False


def test_dialect_marks_drivers_that_are_not_yet_supported():
    answer = node(clustered()).dialect({})
    assert answer['support'] == 'experimental' and 'experimental' in answer['caveats']

    class Supported(ExactListingStore):
        VX_SUPPORT = 'supported'

    answer = node(clustered(Supported)).dialect({})
    assert answer['support'] == 'supported' and 'experimental' not in answer['caveats']


def test_dialect_reports_meta_pending_and_model_mismatch():
    class Pending(ExactListingStore):
        def describe(self):
            import dataclasses

            return dataclasses.replace(super().describe(), meta_column=False)

    store = clustered(Pending)
    store.doesCollectionExist('another-model')
    answer = node(store).dialect({})
    assert answer['health']['meta_column'] is False and answer['health']['model_mismatch'] is True
    assert 'meta_column_pending' in answer['caveats'] and 'model_mismatch' in answer['caveats']


def test_dialect_statement_timeout_is_pgvector_only():
    assert node(clustered()).dialect({})['limits']['statement_timeout_ms'] == 30000
    assert (
        node(clustered(provider='qdrant'), logical_type='qdrant').dialect({})['limits']['statement_timeout_ms'] is None
    )


def test_dialect_store_failure_is_the_only_failure():
    class Broken(MemoryStore):
        def _doesCollectionExist(self):
            raise ConnectionError('connection to server at "10.1.2.3", port 5432 failed')

    answer = node(Broken()).dialect({})
    assert answer['success'] is False and answer['code'] == 'STORE_ERROR'
    assert '10.1.2.3' not in answer['error'] and '5432' not in answer['error']


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_full_extends_the_legacy_answer():
    store = clustered(CountingStore, docs=3, chunks=4)
    answer = node(store).stats({})
    assert answer['success'] is True
    assert answer['count'] == 13  # 12 chunks + the control record: today's meaning
    assert (answer['model'], answer['vector_size']) == (MODEL, 8)
    assert answer['collection_exists'] is True
    assert (answer['documents'], answer['chunks'], answer['deleted_chunks'], answer['tables']) == (3, 12, 0, 0)
    assert answer['documents_without_first_chunk'] == 0
    assert answer['raw_count'] == 13 and answer['avg_chunks_per_document'] == 4.0
    assert (answer['dimension'], answer['metric']) == (8, 'cosine')
    assert answer['computed_at'].endswith('Z') and answer['counts_as_of'] == answer['computed_at']


def test_stats_loads_model_and_dimension_from_the_control_record():
    store = clustered(CountingStore)
    store.vectorSize, store.modelName = 0, ''
    answer = node(store).stats({})
    assert (answer['model'], answer['vector_size']) == (MODEL, 8)


def test_stats_on_a_missing_collection_keeps_the_legacy_success_envelope():
    answer = node(MemoryStore()).stats({})
    assert answer['success'] is True
    assert (answer['count'], answer['model'], answer['vector_size'], answer['collection_exists']) == (0, '', 0, False)
    for key in ('documents', 'chunks', 'deleted_chunks', 'raw_count', 'tables', 'dimension', 'metric', 'counts_as_of'):
        assert answer[key] is None


def test_stats_counts_orphans_and_deleted_chunks():
    store = CountingStore().seed(corpus({'a': [0, 1], 'b': [3, 7], 'c': [0]}))
    store.markDeleted(['c'])
    answer = node(store).stats({})
    assert (answer['documents'], answer['documents_without_first_chunk'], answer['deleted_chunks']) == (2, 1, 1)


def test_stats_without_document_counts_falls_back_to_first_chunks():
    class FirstChunksOnly(CountingStore):
        def countDocuments(self, docFilter):
            return None

    answer = node(FirstChunksOnly().seed(corpus({'a': [0, 1], 'b': [0]}))).stats({})
    assert answer['documents'] == 2
    assert answer['documents_without_first_chunk'] is None
    assert answer['caveats'] == ['documents_by_first_chunk']


def test_stats_on_a_store_that_cannot_count_answers_nulls():
    answer = node(MemoryStore().seed(corpus({'a': [0, 1]}))).stats({})
    assert answer['count'] == 3
    assert (answer['documents'], answer['chunks'], answer['avg_chunks_per_document']) == (None, None, None)
    assert answer['caveats'] == ['no_filtered_count']


def test_stats_quick_returns_cached_figures_with_their_time(monkeypatch):
    store = clustered(CountingStore, docs=2, chunks=2)
    clock = [1_760_000_000.0]
    monkeypatch.setattr(vx_tools, '_wall_clock', lambda: clock[0])
    inst = node(store)
    full = inst.stats({'mode': 'full'})
    store.addChunks([make_doc('new', 0, dim=8)])
    clock[0] += 45
    calls_before = len([c for c in store.calls if c[0] in ('countChunks', 'countDocuments')])
    quick = inst.stats({'mode': 'quick'})
    calls_after = len([c for c in store.calls if c[0] in ('countChunks', 'countDocuments')])
    assert calls_after == calls_before
    assert quick['documents'] == full['documents'] == 2
    assert quick['count'] == full['count'] + 1
    assert quick['counts_as_of'] == full['computed_at'] and quick['computed_at'] != full['computed_at']
    assert inst.stats({'mode': 'full'})['documents'] == 3


def test_stats_quick_without_a_cache_computes_once():
    answer = node(clustered(CountingStore, docs=2, chunks=1)).stats({'mode': 'quick'})
    assert answer['documents'] == 2 and answer['counts_as_of'] is not None


def test_stats_rejects_an_unknown_mode():
    answer = node(clustered()).stats({'mode': 'deep'})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_stats_store_failure_is_a_store_error():
    class Broken(CountingStore):
        def count_documents(self):
            raise RuntimeError('boom')

    answer = node(Broken().seed(corpus({'a': [0]}))).stats({})
    assert (answer['success'], answer['code']) == (False, 'STORE_ERROR')


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


def test_documents_lists_rows_with_paths_and_counts():
    answer = node(clustered(docs=3, chunks=2)).documents({})
    assert answer['success'] is True
    assert [row['objectId'] for row in answer['items']] == ['doc00', 'doc01', 'doc02']
    first = answer['items'][0]
    assert set(first) == {
        'objectId',
        'path',
        'chunks',
        'has_first_chunk',
        'tables',
        'deleted',
        'nodeId',
        'size',
        'modifyTime',
        'ingestedAt',
        'pointId',
    }
    assert (first['path'], first['chunks'], first['has_first_chunk']) == ('C:/demo/folder0/doc00.md', 2, True)
    assert (answer['total'], answer['distinct'], answer['sorted'], answer['counts_exact']) == (3, True, True, True)
    assert answer['caveats'] == [] and answer['next_cursor'] is None


def test_documents_pages_with_the_cursor():
    inst = node(clustered(docs=5, chunks=1))
    first = inst.documents({'limit': 2})
    second = inst.documents({'limit': 2, 'cursor': first['next_cursor']})
    # sorted by path: folder0 holds doc00 and doc03, folder1 doc01 and doc04
    assert [r['objectId'] for r in first['items'] + second['items']] == ['doc00', 'doc03', 'doc01', 'doc04']


def test_documents_default_listing_is_marked_unsorted():
    answer = node(MemoryStore().seed(corpus({'b': [0], 'a': [0]}))).documents({})
    assert answer['sorted'] is False and 'documents_unsorted' in answer['caveats']
    assert all(row['chunks'] is None for row in answer['items'])


def test_documents_on_an_offset_ignoring_store_ends_with_the_paging_caveat():
    inst = node(MemoryStore(ignore_offset=True).seed(corpus({f'd{i}': [0] for i in range(4)})))
    first = inst.documents({'limit': 2})
    second = inst.documents({'limit': 2, 'cursor': first['next_cursor']})
    assert second['items'] == [] and second['next_cursor'] is None
    assert 'documents_paging_unsupported' in second['caveats']


def test_documents_clamps_the_limit_with_a_warning():
    store = clustered(docs=2, chunks=1)
    answer = node(store).documents({'limit': 10_000})
    assert answer['warnings'] == ['limit_clamped']
    assert [c for c in store.calls if c[0] == 'listDocuments'][-1][2] == 500


@pytest.mark.parametrize(
    'args',
    [
        {'cursor': 'not a cursor!'},
        {'cursor': 5},
        {'deleted': 'gone'},
        {'sort': 'size'},
        {'object_ids': 'doc00'},
        {'object_ids': []},
        {'limit': 'many'},
    ],
)
def test_documents_rejects_bad_input(args):
    answer = node(clustered()).documents(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_documents_never_lists_the_control_record():
    answer = node(MemoryStore().seed(corpus({'a': [0]}))).documents({'deleted': 'all'})
    assert 'schema' not in [row['objectId'] for row in answer['items']]


def test_documents_unsupported_listing_is_unsupported():
    class NoListing(MemoryStore):
        def listDocuments(self, **kw):
            raise StoreUnsupported('listDocuments is not supported by this store')

    answer = node(NoListing().seed(corpus({'a': [0]}))).documents({})
    assert (answer['success'], answer['code']) == (False, 'UNSUPPORTED')


# ---------------------------------------------------------------------------
# chunks
# ---------------------------------------------------------------------------


def test_chunks_pages_a_document_in_order():
    inst = node(clustered(docs=1, chunks=5))
    page = inst.chunks({'object_id': 'doc00', 'limit': 2})
    assert page['success'] is True
    assert [item['chunkId'] for item in page['items']] == [0, 1]
    assert (page['has_more'], page['next_after'], page['total']) == (True, 1, 5)
    item = page['items'][0]
    assert set(item) == {'chunkId', 'content', 'length', 'isTable', 'tableId', 'isDeleted', 'pointId', 'metadata'}
    assert item['length'] == len(item['content']) and item['pointId'] == 'pt-doc00-0'
    assert item['metadata']['parent'] == 'C:/demo/folder0/doc00.md'
    rest = inst.chunks({'object_id': 'doc00', 'after_chunk': page['next_after'], 'limit': 10})
    assert [item['chunkId'] for item in rest['items']] == [2, 3, 4] and rest['has_more'] is False


def test_chunks_never_return_vectors():
    page = node(clustered(docs=1, chunks=3)).chunks({'object_id': 'doc00'})
    text = json.dumps(page)
    assert 'embedding' not in text
    assert _no_vectors_anywhere(page, 8)


def test_chunks_of_an_unknown_document_is_not_found():
    answer = node(clustered()).chunks({'object_id': 'nope'})
    assert (answer['success'], answer['code']) == (False, 'NOT_FOUND')
    assert "'nope'" in answer['error']


def test_chunks_of_the_control_record_is_not_found():
    answer = node(clustered()).chunks({'object_id': 'schema'})
    assert (answer['success'], answer['code']) == (False, 'NOT_FOUND')


def test_chunks_existence_probe_succeeds_on_a_document_without_low_chunks():
    answer = node(CountingStore().seed(corpus({'g': [3, 7, 64]}))).chunks({'object_id': 'g', 'limit': 1})
    assert answer['success'] is True and answer['items'] == [] and answer['has_more'] is True


@pytest.mark.parametrize(
    'args', [{}, {'object_id': ''}, {'object_id': 'a', 'after_chunk': -5}, {'object_id': 'a', 'limit': 'x'}]
)
def test_chunks_rejects_bad_input(args):
    answer = node(clustered()).chunks(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_chunks_total_is_null_without_counts():
    answer = node(MemoryStore().seed(corpus({'a': [0, 1]}))).chunks({'object_id': 'a'})
    assert answer['total'] is None


# ---------------------------------------------------------------------------
# vectors
# ---------------------------------------------------------------------------


def test_vectors_returns_at_most_two_raw_vectors():
    store = clustered(docs=2, chunks=1)
    answer = node(store).vectors({'keys': [['doc00', 0], ['doc01', 0]]})
    assert answer['success'] is True and answer['model'] == MODEL
    assert [item['key'] for item in answer['items']] == [['doc00', 0], ['doc01', 0]]
    item = answer['items'][0]
    assert item['dimension'] == 8 and len(item['values']) == 8
    assert item['norm'] == pytest.approx(1.0, abs=1e-5)
    assert item['values'] == pytest.approx(store.rows[('doc00', 0)].embedding)
    assert item['pointId'] == 'pt-doc00-0'


def test_vectors_refuses_more_than_two_keys():
    answer = node(clustered()).vectors({'keys': [['doc00', 0], ['doc00', 1], ['doc00', 2]]})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


@pytest.mark.parametrize('keys', [[['missing', 0]], [['schema', 0]]])
def test_vectors_of_unknown_keys_is_not_found(keys):
    answer = node(clustered()).vectors({'keys': keys})
    assert (answer['success'], answer['code']) == (False, 'NOT_FOUND')


@pytest.mark.parametrize('keys', [None, [], [['doc00']], [['doc00', 'zero']], [[0, 0]], 'doc00'])
def test_vectors_rejects_malformed_keys(keys):
    answer = node(clustered()).vectors({'keys': keys})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_vectors_on_a_store_without_vectors_is_unsupported():
    answer = node(MemoryStore().seed(corpus({'a': [0]}))).vectors({'keys': [['a', 0]]})
    assert (answer['success'], answer['code']) == (False, 'UNSUPPORTED')


# ---------------------------------------------------------------------------
# sample
# ---------------------------------------------------------------------------


def test_sample_detailed_answer_shape():
    store = clustered(docs=6, chunks=5)
    answer = node(store).sample({'n': 20, 'seed': 7})
    assert answer['success'] is True
    assert answer['sample_id'].startswith('s-7-') and len(answer['sample_id']) == len('s-7-') + 8
    assert (answer['n'], answer['n_requested'], answer['mode']) == (20, 20, 'detailed')
    assert answer['of'] == {'chunks': 30, 'documents': 6}
    assert (answer['strategy_used'], answer['biased'], answer['knn_source']) == ('stratified', False, 'node')
    assert (answer['metric'], answer['dimension'], answer['expires_in_s']) == ('cosine', 8, 600)
    points = answer['points']
    assert set(points) == {'doc', 'chunk', 'x', 'y', 'z', 'len', 'snip', 'pinned'}
    assert all(len(points[key]) == 20 for key in points)
    assert answer['knn']['k'] == 15 and len(answer['knn']['offsets_row']) == 21
    assert len(answer['knn']['cols']) == len(answer['knn']['sims']) == 20 * 15
    assert len(answer['density']) == 20 and answer['outliers'] and len(answer['pca']['explained']) == 3
    assert {doc['objectId'] for doc in answer['docs']} == {f'doc{d:02d}' for d in range(6)}
    assert sum(doc['in_sample'] for doc in answer['docs']) == 20
    assert all(doc['chunks'] == 5 for doc in answer['docs'])
    assert 'caveats' not in answer
    assert _no_vectors_anywhere(answer, 8)


def test_sample_points_are_ordered_by_document_then_chunk():
    answer = node(clustered(docs=4, chunks=4)).sample({'n': 12, 'seed': 3})
    pairs = list(zip(answer['points']['doc'], answer['points']['chunk']))
    assert pairs == sorted(pairs)
    paths = [doc['path'] for doc in answer['docs']]
    assert paths == sorted(paths)


def test_sample_takes_the_first_chunk_of_every_document_first():
    answer = node(clustered(docs=6, chunks=5)).sample({'n': 6, 'seed': 1})
    assert sorted(answer['points']['chunk']) == [0] * 6


def test_sample_is_deterministic_for_a_seed():
    store = clustered(docs=5, chunks=6)
    a = node(store).sample({'n': 17, 'seed': 9})
    b = node(store).sample({'n': 17, 'seed': 9})
    for key in ('sample_id', 'points', 'knn', 'density', 'outliers', 'duplicates'):
        assert a[key] == b[key]


def test_sample_light_mode():
    answer = node(clustered(docs=6, chunks=5)).sample({'n': 25, 'mode': 'light', 'knn_k': 25})
    assert answer['mode'] == 'light' and 'snip' not in answer['points']
    assert answer['knn']['k'] == 10 and answer['warnings'] == ['knn_k_clamped']
    assert all(round(v, 2) == v for v in answer['points']['x'])
    assert all(round(v, 2) == v for v in answer['knn']['sims'])


def test_sample_two_components_omit_z():
    answer = node(clustered()).sample({'n': 10, 'components': 2})
    assert 'z' not in answer['points'] and len(answer['pca']['explained']) == 2


def test_sample_snippets_are_cut_to_the_limit():
    answer = node(clustered(docs=2, chunks=3, text_chars=3000)).sample({'n': 6})
    assert all(len(snip) <= 120 and snip.endswith('…') for snip in answer['points']['snip'])
    assert all(length >= 3000 for length in answer['points']['len'])


def test_sample_include_text_false_drops_snippets():
    assert 'snip' not in node(clustered()).sample({'n': 5, 'include_text': False})['points']


def test_sample_pins_include_keys():
    answer = node(clustered(docs=4, chunks=5)).sample({'n': 6, 'include_keys': [['doc03', 4]]})
    pinned = [
        (answer['docs'][d]['objectId'], c)
        for d, c, p in zip(answer['points']['doc'], answer['points']['chunk'], answer['points']['pinned'])
        if p
    ]
    assert pinned == [('doc03', 4)]


def test_sample_scoped_to_object_ids():
    answer = node(clustered(docs=4, chunks=5)).sample({'n': 50, 'filter': {'object_ids': ['doc01', 'doc02']}})
    assert {doc['objectId'] for doc in answer['docs']} == {'doc01', 'doc02'}
    assert answer['n'] == 10 and answer['of'] == {'chunks': 10, 'documents': 2}


def test_sample_uses_a_native_stratified_sampler():
    store = clustered(NativeStratifiedStore, docs=4, chunks=5)
    answer = node(store).sample({'n': 12})
    assert (answer['strategy_used'], answer['biased'], answer['n']) == ('stratified', False, 12)
    assert ('sampleChunks', 'stratified', 12) in store.calls
    assert not any(call[0] == 'getVectors' for call in store.calls)


def test_sample_refills_misses_from_documents_with_gapped_chunk_ids():
    """Listing counts 3 chunks for a document whose ids are {3, 7, 64}: every synthesised key misses."""
    store = ExactListingStore().seed(corpus({'g': [3, 7, 64], 'h': [0, 1, 2]}, dim=8))
    answer = node(store).sample({'n': 6, 'seed': 2})
    assert answer['n'] == 6
    assert (answer['biased'], answer['strategy_used']) == (True, 'random')
    keys = {(answer['docs'][d]['objectId'], c) for d, c in zip(answer['points']['doc'], answer['points']['chunk'])}
    assert keys == {('g', 3), ('g', 7), ('g', 64), ('h', 0), ('h', 1), ('h', 2)}
    assert answer['caveats'] == ['biased_sample']


def test_sample_without_chunk_counts_pins_first_chunks_and_fills_the_rest():
    store = VectorMemoryStore().seed(corpus({'a': [0, 1, 2], 'b': [0, 1, 2], 'c': [0, 1, 2]}, dim=8))
    answer = node(store).sample({'n': 7, 'seed': 4})
    assert answer['n'] == 7 and answer['biased'] is True and answer['strategy_used'] == 'random'
    firsts = {
        answer['docs'][d]['objectId'] for d, c in zip(answer['points']['doc'], answer['points']['chunk']) if c == 0
    }
    assert firsts == {'a', 'b', 'c'}
    assert all(doc['chunks'] is None for doc in answer['docs'])


def test_sample_reports_fewer_points_when_the_collection_is_smaller():
    answer = node(clustered(docs=2, chunks=2)).sample({'n': 50})
    assert (answer['n'], answer['n_requested'], answer['biased']) == (4, 50, False)


def test_sample_marks_planted_duplicates():
    store = ExactListingStore()
    base = _unit([1, 2, 3, 4, 5, 6, 7, 8])
    docs = [make_doc('dup1', 0, vector=base), make_doc('dup2', 0, vector=base)]
    docs += [make_doc(f'o{i}', 0, dim=8) for i in range(6)]
    store.seed(docs)
    answer = node(store).sample({'n': 8})
    index = {d['objectId']: d['i'] for d in answer['docs']}
    point_of = {answer['points']['doc'][p]: p for p in range(answer['n'])}
    pair = sorted([point_of[index['dup1']], point_of[index['dup2']]])
    assert {'a': pair[0], 'b': pair[1], 'sim': 1.0} in answer['duplicates']


@pytest.mark.parametrize(
    'args',
    [
        {'n': 0},
        {'n': 'many'},
        {'mode': 'turbo'},
        {'strategy': 'best'},
        {'components': 4},
        {'duplicate_threshold': 1.5},
        {'include_keys': 'doc00'},
        {'deleted': 'gone'},
        {'filter': {'object_ids': 'doc00'}},
    ],
)
def test_sample_rejects_bad_input(args):
    answer = node(clustered()).sample(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_sample_limits():
    detailed = node(clustered()).sample({'n': 2001})
    light = node(clustered()).sample({'n': 5001, 'mode': 'light'})
    assert (detailed['code'], light['code']) == ('LIMIT_EXCEEDED', 'LIMIT_EXCEEDED')
    assert light['error'] == 'Light mode is limited to 5000 points.'


def test_sample_light_refuses_wide_vectors_above_two_thousand_points():
    store = ExactListingStore().seed([make_doc('wide', 0, dim=8192)])
    answer = node(store).sample({'n': 2500, 'mode': 'light'})
    assert (answer['success'], answer['code']) == (False, 'LIMIT_EXCEEDED')


def test_sample_on_a_missing_collection():
    answer = node(ExactListingStore()).sample({})
    assert (answer['success'], answer['code']) == (False, 'COLLECTION_MISSING')


def test_sample_on_a_store_without_vectors_has_nothing_to_draw():
    answer = node(MemoryStore().seed(corpus({'a': [0, 1]}))).sample({'n': 5})
    assert answer['success'] is True and answer['n'] == 0 and answer['knn']['offsets_row'] == [0]


def test_sample_while_another_runs_is_busy():
    store = clustered()
    inst = node(store)
    cache = vx_tools._vx_state(store).samples()
    with cache.exclusive():
        answer = inst.sample({'n': 5})
    assert (answer['success'], answer['code']) == (False, 'BUSY')


def test_sample_over_its_time_budget_times_out(monkeypatch):
    ticks = iter([0.0] + [10_000.0] * 1000)
    monkeypatch.setattr(vx_tools, '_monotonic', lambda: next(ticks))
    answer = node(clustered()).sample({'n': 10})
    assert (answer['success'], answer['code']) == (False, 'TIMEOUT')


def test_sample_uses_a_native_neighbour_graph():
    class NativeKnn(ExactListingStore):
        def knnGraph(self, keys, vectors, metric, k):
            graph = DocumentStoreBaseKnn(self, keys, vectors, metric, k)
            return graph.__class__(graph.k, graph.offsets_row, graph.cols, graph.sims, 'native')

    answer = node(clustered(NativeKnn)).sample({'n': 10})
    assert answer['knn_source'] == 'native'
    assert node(clustered(NativeKnn)).dialect({})['capabilities']['knn_native'] is True


def DocumentStoreBaseKnn(store, keys, vectors, metric, k):
    return _store_module.DocumentStoreBase.knnGraph(store, keys, vectors, metric, k)


def _payload_bytes(answer: Dict[str, Any]) -> int:
    return len(json.dumps(answer, separators=(',', ':')))


def test_sample_caps_the_near_duplicate_list():
    store = clustered(docs=2, chunks=40, spread=0.01)
    answer = node(store).sample({'n': 80, 'knn_k': 30})
    # two tight clusters of 40: well over a thousand near-duplicate pairs among the kNN edges
    assert len(answer['duplicates']) == vx_tools.DUPLICATES_MAX
    assert 'duplicates_capped' in answer['warnings']
    sims = [pair['sim'] for pair in answer['duplicates']]
    assert sims == sorted(sims, reverse=True)


def test_sample_reports_a_capped_duplicate_list(monkeypatch):
    monkeypatch.setattr(vx_tools, 'DUPLICATES_MAX', 5)
    answer = node(clustered(docs=2, chunks=20, spread=0.01)).sample({'n': 40})
    assert len(answer['duplicates']) == 5 and 'duplicates_capped' in answer['warnings']


def test_sample_payload_detailed_two_thousand_points_fits_one_megabyte():
    store = clustered(docs=40, chunks=50, dim=384, text_chars=3000)
    answer = node(store).sample({'n': 2000, 'knn_k': 15})
    assert answer['n'] == 2000 and answer['knn']['k'] == 15
    assert _payload_bytes(answer) <= 1024 * 1024


def test_sample_payload_light_five_thousand_points_fits_one_megabyte():
    store = clustered(docs=100, chunks=50, dim=384, text_chars=3000)
    answer = node(store).sample({'n': 5000, 'mode': 'light', 'knn_k': 10})
    assert answer['n'] == 5000 and answer['knn']['k'] == 10
    assert _payload_bytes(answer) <= 1024 * 1024


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------


def _sampled(n: int = 12, **kw):
    store = clustered(**kw)
    inst = node(store)
    return store, inst, inst.sample({'n': n, 'seed': 5})


def test_project_a_vector_onto_the_sample():
    store, inst, sample = _sampled()
    vector = store.rows[('doc02', 1)].embedding
    answer = inst.project({'sample_id': sample['sample_id'], 'vector': vector, 'm': 4, 'with_similarities': True})
    assert answer['success'] is True and answer['dimension'] == 8
    item = answer['items'][0]
    assert item['key'] is None and item['in_sample'] is None and len(item['pca']) == 3
    assert len(item['neighbors']) == 4
    sims = [nb['sim'] for nb in item['neighbors']]
    assert sims == sorted(sims, reverse=True)
    assert len(answer['similarities']) == sample['n']
    assert max(answer['similarities']) == pytest.approx(sims[0], abs=1e-4)


def test_project_keys_in_and_out_of_the_sample():
    store, inst, sample = _sampled(n=6)
    point0 = (sample['docs'][sample['points']['doc'][0]]['objectId'], sample['points']['chunk'][0])
    outside = ('doc05', 4)
    answer = inst.project({'sample_id': sample['sample_id'], 'keys': [list(point0), list(outside)], 'm': 3})
    inside_item, outside_item = answer['items']
    assert inside_item['in_sample'] == 0 and inside_item['key'] == list(point0)
    assert all(nb['i'] != 0 for nb in inside_item['neighbors'])
    assert inside_item['pca'] == pytest.approx(
        [sample['points']['x'][0], sample['points']['y'][0], sample['points']['z'][0]], abs=2e-4
    )
    assert outside_item['in_sample'] is None and outside_item['key'] == list(outside)
    assert 'similarities' not in answer


def test_project_lists_keys_it_cannot_find():
    _store, inst, sample = _sampled()
    answer = inst.project({'sample_id': sample['sample_id'], 'keys': [['doc00', 0], ['ghost', 3]]})
    assert answer['not_found'] == [['ghost', 3]]
    missing = inst.project({'sample_id': sample['sample_id'], 'keys': [['ghost', 3]]})
    assert (missing['success'], missing['code']) == (False, 'NOT_FOUND')


def test_project_on_an_expired_sample():
    _store, inst, _sample = _sampled()
    answer = inst.project({'sample_id': 's-1-deadbeef', 'vector': [0.1] * 8})
    assert (answer['success'], answer['code']) == (False, 'SAMPLE_EXPIRED')


def test_project_with_the_wrong_dimension():
    _store, inst, sample = _sampled()
    answer = inst.project({'sample_id': sample['sample_id'], 'vector': [0.1] * 5})
    assert (answer['success'], answer['code']) == (False, 'DIMENSION_MISMATCH')


@pytest.mark.parametrize(
    'extra',
    [{}, {'vector': [0.1] * 8, 'keys': [['doc00', 0]]}, {'vector': ['a'] * 8}, {'keys': [['doc00']]}],
)
def test_project_rejects_bad_input(extra):
    _store, inst, sample = _sampled()
    answer = inst.project({'sample_id': sample['sample_id'], **extra})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_project_without_a_sample_id_is_invalid():
    answer = node(clustered()).project({'vector': [0.1] * 8})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_project_while_a_sample_runs_is_busy():
    store, inst, sample = _sampled()
    with vx_tools._vx_state(store).samples().exclusive():
        answer = inst.project({'sample_id': sample['sample_id'], 'vector': [0.1] * 8})
    assert (answer['success'], answer['code']) == (False, 'BUSY')


# ---------------------------------------------------------------------------
# neighbors
# ---------------------------------------------------------------------------


def test_neighbors_of_a_key_across_the_collection():
    store = clustered(docs=4, chunks=5)
    answer = node(store).neighbors({'key': ['doc01', 2], 'k': 5})
    assert answer['success'] is True
    assert (answer['metric'], answer['scope'], answer['k_requested']) == ('cosine', 'collection', 5)
    items = answer['items']
    assert len(items) == 5 and ['doc01', 2] not in [item['key'] for item in items]
    assert [item['sim'] for item in items] == sorted((item['sim'] for item in items), reverse=True)
    first = items[0]
    assert set(first) == {'key', 'sim', 'score', 'below_floor', 'path', 'chunkId', 'preview'}
    assert first['key'][0] == 'doc01' and first['path'] == 'C:/demo/folder1/doc01.md'
    assert len(first['preview']) <= 120


def test_neighbors_include_rows_below_the_floor():
    store = VectorMemoryStore().seed(
        [make_doc('a', 0, vector=[1, 0]), make_doc('b', 0, vector=[0.1, 1]), make_doc('c', 0, vector=[-1, 0.05])]
    )
    answer = node(store).neighbors({'key': ['a', 0], 'k': 5})
    assert [item['key'][0] for item in answer['items']] == ['b', 'c']
    assert [item['below_floor'] for item in answer['items']] == [True, True]
    semantic = [call for call in store.calls if call[0] == 'semantic'][-1]
    assert semantic[2].minScore == float('-inf')


def test_neighbors_can_include_the_point_itself():
    answer = node(clustered()).neighbors({'key': ['doc00', 0], 'k': 3, 'exclude_self': False})
    assert answer['items'][0]['key'] == ['doc00', 0] and answer['items'][0]['sim'] == pytest.approx(1.0)


def test_neighbors_of_a_vector():
    store = clustered()
    answer = node(store).neighbors({'vector': store.rows[('doc03', 1)].embedding, 'k': 2})
    assert answer['items'][0]['key'] == ['doc03', 1]


def test_neighbors_scope_scores_in_key_order():
    store = clustered(docs=2, chunks=2)
    answer = node(store).neighbors({'key': ['doc00', 0], 'scope_keys': [['doc00', 0], ['doc01', 1], ['ghost', 0]]})
    assert answer['success'] is True and set(answer) == {'success', 'scores'}
    assert answer['scores'][0] == pytest.approx(1.0) and answer['scores'][2] is None


def test_neighbors_of_an_unknown_key():
    answer = node(clustered()).neighbors({'key': ['ghost', 0]})
    assert (answer['success'], answer['code']) == (False, 'NOT_FOUND')


def test_neighbors_with_the_wrong_dimension():
    answer = node(clustered()).neighbors({'vector': [0.1, 0.2]})
    assert (answer['success'], answer['code']) == (False, 'DIMENSION_MISMATCH')


@pytest.mark.parametrize('args', [{}, {'key': ['doc00', 0], 'vector': [0.1] * 8}, {'key': 'doc00'}, {'vector': []}])
def test_neighbors_rejects_bad_input(args):
    answer = node(clustered()).neighbors(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_neighbors_on_a_missing_collection():
    answer = node(VectorMemoryStore()).neighbors({'vector': [0.1] * 8})
    assert (answer['success'], answer['code']) == (False, 'COLLECTION_MISSING')


def test_neighbors_one_at_a_time():
    store = clustered()
    lock = vx_tools._vx_state(store).neighbors_busy
    assert lock.acquire(blocking=False)
    try:
        answer = node(store).neighbors({'key': ['doc00', 0]})
    finally:
        lock.release()
    assert (answer['success'], answer['code']) == (False, 'BUSY')


def test_neighbors_clamps_k():
    answer = node(clustered()).neighbors({'key': ['doc00', 0], 'k': 500})
    assert answer['k_requested'] == 50 and answer['warnings'] == ['k_clamped']


# ---------------------------------------------------------------------------
# search (legacy descriptor, additive answer)
# ---------------------------------------------------------------------------


def test_search_legacy_answer_gains_success_rank_and_mode():
    store = clustered()
    inst = node(store, embed_query=lambda text: store.rows[('doc01', 0)].embedding, embed_model_name=MODEL)
    answer = inst.search({'query': 'kestrel', 'top_k': 3})
    assert answer['success'] is True and answer['mode_used'] == 'semantic' and answer['warnings'] == []
    assert [item['rank'] for item in answer['results']] == [1, 2, 3]
    assert set(answer['results'][0]) == {'content', 'score', 'metadata', 'rank'}
    assert set(answer['results'][0]['metadata']) == {'objectId', 'nodeId', 'parent', 'chunkId'}


def test_search_with_a_vector():
    store = clustered()
    vector = store.rows[('doc02', 3)].embedding
    answer = node(store).search({'vector': vector, 'top_k': 4})
    assert answer['success'] is True and answer['mode_used'] == 'semantic'
    first = answer['results'][0]
    assert first['metadata']['objectId'] == 'doc02' and first['metadata']['chunkId'] == 3
    assert set(first) >= {'raw_score', 'sim', 'below_threshold', 'below_floor', 'rank'}
    assert first['sim'] == pytest.approx(1.0, abs=1e-4) and first['raw_score'] == first['score']
    scores = [item['score'] for item in answer['results']]
    assert scores == sorted(scores, reverse=True)


def test_search_with_a_vector_can_include_rows_below_the_floor():
    store = VectorMemoryStore().seed([make_doc('a', 0, vector=[1, 0]), make_doc('b', 0, vector=[-1, 0.1])])
    plain = node(store).search({'vector': [1, 0]})
    everything = node(store).search({'vector': [1, 0], 'include_below_floor': True})
    assert [r['metadata']['objectId'] for r in plain['results']] == ['a']
    assert [r['metadata']['objectId'] for r in everything['results']] == ['a', 'b']
    assert everything['results'][1]['below_floor'] is True and everything['results'][1]['below_threshold'] is True


def test_search_warns_on_a_model_mismatch():
    store = clustered()
    answer = node(store).search({'vector': store.rows[('doc00', 0)].embedding, 'embedding_model': 'other-model'})
    assert answer['success'] is True and answer['warnings'] == ['model_mismatch']


def test_search_keyword_fallback_is_reported():
    store = clustered()
    store.raise_semantic = RuntimeError('the embedding model is not loaded')
    answer = node(store).search({'vector': store.rows[('doc00', 0)].embedding, 'query': 'doc00'})
    assert answer['mode_used'] == 'keyword'
    assert answer['warnings'] == [
        'keyword_fallback',
        'semantic search failed: RuntimeError: the embedding model is not loaded',
    ]


def test_search_semantic_mode_does_not_fall_back():
    store = clustered()
    store.raise_semantic = RuntimeError('boom')
    answer = node(store).search({'vector': store.rows[('doc00', 0)].embedding, 'mode': 'semantic'})
    assert (answer['success'], answer['code']) == (False, 'STORE_ERROR')


def test_search_keyword_mode_needs_no_embedder():
    answer = node(clustered()).search({'query': 'doc04 chunk 2', 'mode': 'keyword'})
    assert answer['mode_used'] == 'keyword' and answer['results'][0]['metadata']['objectId'] == 'doc04'


def test_search_keyword_unsupported():
    store = clustered()
    store.keyword_unsupported = True
    answer = node(store).search({'query': 'x', 'mode': 'keyword'})
    assert (answer['success'], answer['code']) == (False, 'UNSUPPORTED')


def test_search_without_an_embedder_is_no_embedder():
    answer = node(clustered()).search({'query': 'kestrel'})
    assert (answer['success'], answer['code']) == (False, 'NO_EMBEDDER')
    assert 'embedding' in answer['error']


def test_search_with_the_wrong_dimension():
    answer = node(clustered()).search({'vector': [0.1, 0.2, 0.3]})
    assert (answer['success'], answer['code']) == (False, 'DIMENSION_MISMATCH')
    assert answer['error'] == 'The vector has 3 values; this collection stores 8.'


def test_search_with_a_vector_on_a_missing_collection():
    answer = node(VectorMemoryStore()).search({'vector': [0.1, 0.2]})
    assert (answer['success'], answer['code']) == (False, 'COLLECTION_MISSING')


@pytest.mark.parametrize(
    'args',
    [
        {},
        {'query': '   '},
        {'vector': []},
        {'vector': ['x']},
        {'query': 'a', 'mode': 'fuzzy'},
        {'query': 'a', 'deleted': 'x'},
    ],
)
def test_search_rejects_bad_input(args):
    answer = node(clustered()).search(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_search_extended_filter_reaches_the_store():
    store = clustered()
    node(store).search(
        {
            'vector': store.rows[('doc00', 0)].embedding,
            'filter': {'objectIds': ['doc00', 'doc01'], 'isTable': False, 'minChunkId': 1, 'maxChunkId': 3},
            'deleted': 'all',
        }
    )
    flt = [call for call in store.calls if call[0] == 'semantic'][-1][2]
    assert flt.objectIds == ['doc00', 'doc01'] and flt.isTable is False
    assert (flt.minChunkId, flt.maxChunkId, flt.deleted, flt.isDeleted) == (1, 3, 'all', True)


def test_search_never_returns_the_control_record():
    store = clustered()
    answer = node(store).search({'vector': [0.0] * 8, 'include_below_floor': True, 'deleted': 'all', 'top_k': 100})
    assert 'schema' not in [r['metadata']['objectId'] for r in answer['results']]


# ---------------------------------------------------------------------------
# remove_document
# ---------------------------------------------------------------------------


def test_remove_document_removes_and_reports_rows(context):
    context(dap())
    store = clustered(CountingStore, docs=3, chunks=4)
    answer = node(store, allow_writes=True).remove_document({'object_ids': ['doc01', 'ghost']})
    assert answer['success'] is True
    assert answer['removed'] == [{'objectId': 'doc01', 'chunks_removed': 4}]
    assert answer['not_found'] == ['ghost'] and answer['removed_chunks'] == 4
    assert not any(key[0] == 'doc01' for key in store.rows)
    assert answer['audit'] == {
        'action': 'vector.remove_document',
        'node': 'store_1',
        'provider': 'postgres',
        'collection': 'vx_test_docs',
        'object_ids': ['doc01', 'ghost'],
        'rows': 4,
        'caller': {'auth': 'account', 'userId': 'u-0001', 'teamId': 't-0001'},
    }


def test_remove_document_audit_carries_no_content(context):
    context(dap())
    answer = node(clustered(CountingStore), allow_writes=True).remove_document({'object_ids': ['doc00']})
    text = json.dumps(answer['audit'])
    assert 'lorem' not in text and 'chunk' not in text and 'embedding' not in text
    assert set(answer['audit']) == {'action', 'node', 'provider', 'collection', 'object_ids', 'rows', 'caller'}


def test_remove_document_without_counts_reports_unknown_rows(context):
    context(dap())
    store = MemoryStore().seed(corpus({'a': [0, 1], 'b': [0]}))
    answer = node(store, allow_writes=True).remove_document({'object_ids': ['a', 'b']})
    assert answer['removed'] == [{'objectId': 'a', 'chunks_removed': None}, {'objectId': 'b', 'chunks_removed': None}]
    assert answer['removed_chunks'] is None and answer['not_found'] == []
    assert not any(key[0] in ('a', 'b') for key in store.rows)


def test_remove_document_single_document_takes_the_driver_count(context):
    context(dap())

    class Returning(MemoryStore):
        def removeCounted(self, objectIds):
            self.remove(objectIds)
            return 2

    answer = node(Returning().seed(corpus({'a': [0, 1]})), allow_writes=True).remove_document({'object_ids': ['a']})
    assert answer['removed'] == [{'objectId': 'a', 'chunks_removed': 2}] and answer['removed_chunks'] == 2


def test_remove_document_reserved_id(context):
    context(dap())
    store = clustered(CountingStore)
    before = dict(store.rows)
    answer = node(store, allow_writes=True).remove_document({'object_ids': ['schema']})
    assert (answer['success'], answer['code']) == (False, 'RESERVED_ID')
    assert store.rows.keys() == before.keys()


@pytest.mark.parametrize(
    'ctx,switches,code',
    [
        (None, {'allow_writes': True}, 'WRITES_UNKNOWN_CALLER'),
        (dap(), {}, 'WRITES_DISABLED'),
        (dap(), {'allow_writes': False}, 'WRITES_DISABLED'),
        (dap(source_type='chat'), {'allow_writes': True}, 'WRITES_SOURCE'),
        (dap(source_type=None), {'allow_writes': True}, 'WRITES_SOURCE'),
        (dap(auth='public'), {'allow_writes': True}, 'WRITES_PUBLIC'),
        (dap(targeted=False), {'allow_writes': True}, 'WRITES_BROADCAST'),
        (agent(), {'agent_writes': False}, 'WRITES_AGENT'),
    ],
)
@pytest.mark.parametrize('tool', ['remove_document', 'delete'])
def test_refused_removals_leave_the_data_unchanged(context, ctx, switches, code, tool):
    context(ctx)
    store = clustered(CountingStore, docs=2, chunks=2)
    before = {key: doc.model_dump() for key, doc in store.rows.items()}
    answer = getattr(node(store, **switches), tool)({'object_ids': ['doc00']})
    assert (answer['success'], answer['code']) == (False, code)
    assert {key: doc.model_dump() for key, doc in store.rows.items()} == before
    assert not any(call[0] == 'remove' for call in store.calls)


@pytest.mark.parametrize(
    'ctx,switches,code',
    [
        (None, {'allow_writes': True}, 'WRITES_UNKNOWN_CALLER'),
        (dap(), {}, 'WRITES_DISABLED'),
        (dap(source_type='dropper'), {'allow_writes': True}, 'WRITES_SOURCE'),
        (dap(auth='public'), {'allow_writes': True}, 'WRITES_PUBLIC'),
        (dap(targeted=False), {'allow_writes': True}, 'WRITES_BROADCAST'),
        (agent(), {'agent_writes': False}, 'WRITES_AGENT'),
    ],
)
def test_refused_upserts_leave_the_data_unchanged(context, ctx, switches, code):
    context(ctx)
    store = clustered(CountingStore, docs=1, chunks=1)
    before = set(store.rows)
    inst = node(store, embed_query=lambda text: [0.1] * 8, embed_model_name=MODEL, **switches)
    answer = inst.upsert({'documents': [{'content': 'new text', 'object_id': 'fresh'}]})
    assert (answer['success'], answer['code']) == (False, code)
    assert set(store.rows) == before


def test_a_forged_context_inside_the_input_is_ignored(context):
    context(None)
    store = clustered(CountingStore)
    forged = {'origin': 'agent', 'source_type': 'tools', 'targeted': True, 'caller': {'auth': 'account'}}
    answer = node(store, allow_writes=True).remove_document({'object_ids': ['doc00'], '__tool_context__': forged})
    assert (answer['success'], answer['code']) == (False, 'WRITES_UNKNOWN_CALLER')
    assert any(key[0] == 'doc00' for key in store.rows)


@pytest.mark.parametrize('ids', [None, [], 'doc00', [''], [1, 2], ['x'] * 0, [f'd{i}' for i in range(101)]])
def test_remove_document_rejects_bad_ids(context, ids):
    context(dap())
    answer = node(clustered(CountingStore), allow_writes=True).remove_document({'object_ids': ids})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_remove_document_resets_the_cached_counts(context, monkeypatch):
    context(dap())
    store = clustered(CountingStore, docs=3, chunks=1)
    inst = node(store, allow_writes=True)
    assert inst.stats({})['documents'] == 3
    inst.remove_document({'object_ids': ['doc00']})
    assert inst.stats({'mode': 'quick'})['documents'] == 2


def test_agent_removal_with_default_switches_is_allowed(context):
    context(agent())
    answer = node(clustered(CountingStore)).remove_document({'object_ids': ['doc00']})
    assert answer['success'] is True
    assert answer['audit']['caller'] == {'auth': 'agent', 'userId': None, 'teamId': None}


# ---------------------------------------------------------------------------
# delete / upsert (legacy descriptors, gated, extended answers)
# ---------------------------------------------------------------------------


def test_delete_extended_answer(context):
    context(dap())
    store = clustered(CountingStore, docs=2, chunks=3)
    answer = node(store, allow_writes=True).delete({'object_ids': ['doc00', 'doc00', 'ghost']})
    assert answer['success'] is True
    assert (answer['deleted_count'], answer['removed_chunks'], answer['not_found']) == (3, 3, ['ghost'])
    assert answer['audit']['action'] == 'vector.delete' and answer['audit']['object_ids'] == ['doc00', 'ghost']


def test_delete_refuses_the_control_record(context):
    context(agent())
    answer = node(clustered(CountingStore)).delete({'object_ids': ['doc00', 'schema']})
    assert (answer['success'], answer['code']) == (False, 'RESERVED_ID')


def test_upsert_from_dap_with_a_caller_embedding_is_invalid(context):
    context(dap())
    store = clustered(CountingStore)
    answer = node(store, allow_writes=True).upsert(
        {'documents': [{'content': 'x', 'object_id': 'n', 'embedding': [0.1] * 8, 'embedding_model': MODEL}]}
    )
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')
    assert ('n', 0) not in store.rows


def test_upsert_refuses_the_control_record(context):
    context(agent())
    answer = node(clustered(CountingStore), embed_query=lambda t: [0.1] * 8).upsert(
        {'documents': [{'content': 'x', 'object_id': 'schema'}]}
    )
    assert (answer['success'], answer['code']) == (False, 'RESERVED_ID')


def test_upsert_from_the_tools_source_with_writes_on(context):
    context(dap(auth='task'))
    store = clustered(CountingStore)
    inst = node(store, allow_writes=True, embed_query=lambda t: [0.2] * 8, embed_model_name=MODEL)
    answer = inst.upsert({'documents': [{'content': 'fresh text', 'object_id': 'fresh'}]})
    assert (answer['success'], answer['count'], answer['skipped']) == (True, 1, 0)
    assert answer['audit']['action'] == 'vector.upsert' and answer['audit']['caller']['auth'] == 'task'
    assert ('fresh', 0) in store.rows


def test_upsert_store_error_is_enveloped(agent_context):
    class Failing(CountingStore):
        def addChunks(self, chunks, checkCollection=True):
            raise RuntimeError('model mismatch')

    inst = node(Failing(), embed_query=lambda t: [0.1] * 8, embed_model_name=MODEL)
    answer = inst.upsert({'documents': [{'content': 'x', 'object_id': 'a'}]})
    assert (answer['success'], answer['code']) == (False, 'STORE_ERROR')
    assert 'model mismatch' in answer['error']


def test_upsert_without_an_embedder_is_no_embedder(agent_context):
    answer = node(clustered(CountingStore)).upsert({'documents': [{'content': 'x', 'object_id': 'a'}]})
    assert (answer['success'], answer['code']) == (False, 'NO_EMBEDDER')


# ---------------------------------------------------------------------------
# get / objdir (legacy descriptors, fixed)
# ---------------------------------------------------------------------------


def test_get_pages_in_chunk_order_with_has_more():
    inst = node(clustered(docs=1, chunks=5))
    first = inst.get({'object_id': 'doc00', 'limit': 2})
    assert [c['chunkId'] for c in first['chunks']] == [0, 1] and first['has_more'] is True and first['total'] == 2
    rest = inst.get({'object_id': 'doc00', 'offset': 2, 'limit': 10})
    assert [c['chunkId'] for c in rest['chunks']] == [2, 3, 4] and rest['has_more'] is False
    assert set(first['chunks'][0]) == {'content', 'chunkId', 'metadata'}
    assert first['chunks'][0]['metadata']['objectId'] == 'doc00'


def test_get_clamps_the_limit():
    store = clustered(docs=1, chunks=3)
    node(store).get({'object_id': 'doc00', 'limit': 100_000})
    window = [call for call in store.calls if call[0] == 'get'][0][1]
    assert window.maxChunkId - window.minChunkId + 1 == 200


@pytest.mark.parametrize(
    'args', [{}, {'object_id': ''}, {'object_id': 'doc00', 'offset': 'x'}, {'object_id': 'doc00', 'limit': 'x'}]
)
def test_get_rejects_bad_input(args):
    answer = node(clustered()).get(args)
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_get_of_the_control_record_is_empty():
    answer = node(clustered()).get({'object_id': 'schema'})
    assert answer['success'] is True and answer['chunks'] == [] and answer['has_more'] is False


def test_objdir_lists_entries_without_collapsing_equal_paths():
    store = MemoryStore().seed(
        [make_doc('a', 0, path='/same.md'), make_doc('b', 0, path='/same.md'), make_doc('c', 0, path='/other.md')]
    )
    answer = node(store).objdir({})
    assert answer['success'] is True
    assert sorted((e['path'], e['objectId']) for e in answer['entries']) == [
        ('/other.md', 'c'),
        ('/same.md', 'a'),
        ('/same.md', 'b'),
    ]
    assert set(answer['paths']) == {'/same.md', '/other.md'}


def test_objdir_excludes_the_control_record_and_deleted_documents():
    store = MemoryStore().seed(corpus({'a': [0], 'b': [0]}))
    store.markDeleted(['b'])
    answer = node(store).objdir({})
    assert [e['objectId'] for e in answer['entries']] == ['a']
    assert 'schema' not in answer['paths'].values()


def test_objdir_filters_by_parent_prefix_and_pages():
    store = MemoryStore().seed(
        [make_doc(f'd{i}', 0, path=f'/docs/{i}.md') for i in range(5)] + [make_doc('x', 0, path='/x.md')]
    )
    answer = node(store).objdir({'parent': '/docs/', 'offset': 1, 'limit': 2})
    assert [e['objectId'] for e in answer['entries']] == ['d1', 'd2']


def test_objdir_rejects_bad_integers():
    answer = node(clustered()).objdir({'limit': 'lots'})
    assert (answer['success'], answer['code']) == (False, 'INVALID_INPUT')


def test_objdir_clamps_the_limit():
    store = MemoryStore().seed(corpus({f'd{i}': [0] for i in range(3)}))
    assert len(node(store).objdir({'limit': 0})['entries']) == 1


# ---------------------------------------------------------------------------
# concurrency smoke: a sample and a neighbour search on one store
# ---------------------------------------------------------------------------


def test_sample_and_neighbors_use_separate_gates():
    store = clustered()
    inst = node(store)
    results: Dict[str, Any] = {}
    with vx_tools._vx_state(store).samples().exclusive():
        thread = threading.Thread(target=lambda: results.setdefault('n', inst.neighbors({'key': ['doc00', 0]})))
        thread.start()
        thread.join(10)
    assert results['n']['success'] is True
