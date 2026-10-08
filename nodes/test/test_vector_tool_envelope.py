# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""The envelope every vector store tool answers in, and what agents see.

* ``vectordb_tool`` turns every outcome into ``{success, ...}`` or
  ``{success: false, code, error}``: ``StoreUnsupported`` -> ``UNSUPPORTED``,
  ``ToolRefusal`` -> its code, any other ``BaseException`` -> ``STORE_ERROR``;
  ``KeyboardInterrupt``/``SystemExit`` still propagate. Nothing else escapes.
* Answers are JSON: numpy becomes lists and numbers, NaN/inf become null, and an
  answer over the size cap is refused with ``LIMIT_EXCEEDED``.
* Error text never carries a URL, DSN, host, port or credential.
* The explorer tools are listed for external callers only; the six agent tools
  keep their descriptors byte for byte (pinned by a hash of today's catalog).
"""

from __future__ import annotations

import hashlib
import json
import math
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from rocketlib import IInstanceBase, tool_function

from ai.common.store import VectorStoreToolMixin, vx_tools
from ai.common.store.errors import StoreError, StoreUnsupported, ToolRefusal
from ai.common.store.vx_types import TOOL_CODES

from .test_vector_hooks import MemoryStore, corpus

#: sha256 of today's six agent descriptors (search, upsert, delete, objdir, get, stats) as
#: ``_build_tool_descriptors`` builds them, JSON with sorted keys and no spaces.
LEGACY_AGENT_CATALOG_SHA256 = 'ac5b61b8273890e938c91c5c090c9dc292e8de685c39ff6d86ba231de218b4b7'

LEGACY_TOOLS = ('delete', 'get', 'objdir', 'search', 'stats', 'upsert')
EXPLORER_TOOLS = ('chunks', 'dialect', 'documents', 'neighbors', 'project', 'remove_document', 'sample', 'vectors')


class _Probe:
    """A host for wrapped methods that raise whatever a test asks for."""

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    @vx_tools.vectordb_tool
    def run(self, args):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome(args)
        return self.outcome


def _run(outcome: Any, args: Any = None):
    return _Probe(outcome).run(args)


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------


def test_success_answers_pass_through_with_success_first():
    answer = _run({'value': 1, 'success': True})
    assert list(answer) == ['success', 'value'] and answer == {'success': True, 'value': 1}


def test_an_answer_without_success_gains_it():
    assert _run({'results': []}) == {'success': True, 'results': []}


def test_store_unsupported_becomes_unsupported():
    assert _run(StoreUnsupported('getVectors is not supported by this store')) == {
        'success': False,
        'code': 'UNSUPPORTED',
        'error': 'getVectors is not supported by this store',
    }


def test_tool_refusal_becomes_its_code_with_extra_keys():
    answer = _run(ToolRefusal('RATE_LIMITED', 'Too many calls.', {'retry_after_s': 12}))
    assert answer == {'success': False, 'code': 'RATE_LIMITED', 'error': 'Too many calls.', 'retry_after_s': 12}


@pytest.mark.parametrize(
    'exc', [RuntimeError('boom'), StoreError('backend failed'), ValueError('bad'), KeyError('k'), ZeroDivisionError()]
)
def test_other_exceptions_become_store_error(exc):
    answer = _run(exc)
    assert (answer['success'], answer['code']) == (False, 'STORE_ERROR')
    assert answer['error'].startswith(type(exc).__name__)


def test_a_bare_base_exception_never_escapes():
    class DriverAbort(BaseException):
        pass

    answer = _run(DriverAbort('non-zero offset'))
    assert answer == {'success': False, 'code': 'STORE_ERROR', 'error': 'DriverAbort: non-zero offset'}


def test_generator_exit_is_contained_too():
    assert _run(GeneratorExit())['code'] == 'STORE_ERROR'


@pytest.mark.parametrize('exc', [KeyboardInterrupt(), SystemExit(3)])
def test_interrupts_and_exits_propagate(exc):
    with pytest.raises(type(exc)):
        _run(exc)


def test_the_wrapper_normalises_the_input():
    seen = {}

    def capture(args):
        seen.update(args)
        return {'ok': True}

    _run(capture, '{"input": {"a": 1}, "b": 2, "security_context": {"x": 1}}')
    assert seen == {'a': 1, 'b': 2}


def test_the_wrapper_keeps_the_name_and_docstring():
    assert _Probe.run.__name__ == 'run'
    assert getattr(_Probe.run, '__vectordb_tool__', False) is True


# ---------------------------------------------------------------------------
# JSON post-processing
# ---------------------------------------------------------------------------


def test_numpy_values_become_json():
    answer = _run(
        {
            'array': np.array([1.5, 2.5], dtype=np.float32),
            'matrix': np.eye(2, dtype=np.int64),
            'scalar': np.float32(0.25),
            'integer': np.int64(7),
            'flag': np.bool_(True),
            'nested': {'tuple': (1, 2), 'set': {'b', 'a'}},
        }
    )
    assert answer['array'] == [1.5, 2.5] and answer['matrix'] == [[1, 0], [0, 1]]
    assert answer['scalar'] == 0.25 and answer['integer'] == 7 and answer['flag'] is True
    assert type(answer['integer']) is int and type(answer['flag']) is bool
    assert answer['nested'] == {'tuple': [1, 2], 'set': ['a', 'b']}
    json.dumps(answer, allow_nan=False)


def test_non_finite_numbers_become_null():
    answer = _run({'a': math.nan, 'b': [math.inf, -math.inf, 1.0], 'c': np.array([np.nan, 2.0])})
    assert answer == {'success': True, 'a': None, 'b': [None, None, 1.0], 'c': [None, 2.0]}


def test_bytes_never_reach_the_answer():
    assert _run({'blob': b'\x00\x01'})['blob'] is None


def test_an_oversized_answer_is_refused(monkeypatch):
    monkeypatch.setattr(vx_tools, 'MAX_ANSWER_BYTES', 100)
    answer = _run({'items': ['x' * 200]})
    assert (answer['success'], answer['code']) == (False, 'LIMIT_EXCEEDED')


def test_the_size_cap_is_eight_megabytes():
    assert vx_tools.MAX_ANSWER_BYTES == 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# Error text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'message,secrets',
    [
        ('connection to server at "10.0.0.5", port 55432 failed', ['10.0.0.5', '55432']),
        (
            'could not connect to postgresql://rruser:rrpass@db.internal:5432/rrtenant',
            ['rrpass', 'db.internal', 'rrtenant'],
        ),
        (
            'host=db.internal port=5432 dbname=tenant_7 user=admin password=s3cret',
            ['db.internal', 'tenant_7', 's3cret', 'admin'],
        ),
        ('failed to reach http://localhost:6333/collections', ['localhost', '6333']),
        ('could not translate host name "vectors.example.com" to address', ['vectors.example.com']),
        ('apikey=abc123 rejected', ['abc123']),
        ('connect to [::1]:19530 refused', ['::1', '19530']),
    ],
)
def test_error_text_is_scrubbed(message, secrets):
    answer = _run(RuntimeError(message))
    for secret in secrets:
        assert secret not in answer['error']


def test_error_text_is_bounded():
    assert len(vx_tools.safe_error_text('x ' * 1000)) <= 300


def test_plain_error_text_is_kept():
    assert vx_tools.safe_error(ValueError('the vector has 3 values')) == 'ValueError: the vector has 3 values'


# ---------------------------------------------------------------------------
# Every tool, every failure: an envelope, never an exception
# ---------------------------------------------------------------------------


class Node(VectorStoreToolMixin, IInstanceBase):
    pass


def _node(store: Any) -> Node:
    inst = object.__new__(Node)
    inst.IGlobal = SimpleNamespace(store=store, glb=SimpleNamespace(logicalType='postgres'), allow_writes=True)
    inst.instance = SimpleNamespace(pipeType={'id': 'store_1'})
    return inst


_INPUTS = {
    'dialect': {},
    'stats': {},
    'documents': {},
    'chunks': {'object_id': 'a'},
    'vectors': {'keys': [['a', 0]]},
    'sample': {'n': 5},
    'project': {'sample_id': 's-1-aaaaaaaa', 'vector': [0.1, 0.2]},
    'neighbors': {'vector': [0.1, 0.2]},
    'search': {'vector': [0.1, 0.2]},
    'remove_document': {'object_ids': ['a']},
    'delete': {'object_ids': ['a']},
    'upsert': {'documents': [{'content': 'x', 'object_id': 'a'}]},
    'get': {'object_id': 'a'},
    'objdir': {},
}


def test_every_tool_has_an_input_case():
    assert set(_INPUTS) == set(LEGACY_TOOLS) | set(EXPLORER_TOOLS)


@pytest.mark.parametrize('tool', sorted(_INPUTS))
def test_every_tool_answers_an_envelope_when_the_store_is_not_open(tool):
    answer = getattr(_node(None), tool)(_INPUTS[tool])
    assert answer['success'] is False and answer['code'] in TOOL_CODES and answer['error']


class _Exploding(MemoryStore):
    """A store whose every backend call fails."""

    def __getattribute__(self, name):
        if name in {
            '_doesCollectionExist',
            'get',
            'count_documents',
            'searchSemantic',
            'searchKeyword',
            'remove',
            'addChunks',
            'getPaths',
        }:

            def boom(*a, **kw):
                raise OSError('connection to server at "10.9.9.9", port 5432 failed')

            return boom
        return super().__getattribute__(name)


@pytest.mark.parametrize('tool', sorted(_INPUTS))
def test_every_tool_answers_an_envelope_when_the_backend_fails(tool, monkeypatch):
    from ai.common.store import vx_write_gate

    monkeypatch.setattr(
        vx_write_gate,
        '_current_tool_call',
        lambda: {'origin': 'dap', 'source_type': 'tools', 'targeted': True, 'caller': {'auth': 'account'}},
    )
    answer = getattr(_node(_Exploding()), tool)(_INPUTS[tool])
    assert answer['success'] is False and answer['code'] in TOOL_CODES
    assert '10.9.9.9' not in json.dumps(answer)


@pytest.mark.parametrize('tool', sorted(_INPUTS))
def test_every_tool_answer_is_strict_json(tool):
    store = MemoryStore().seed(corpus({'a': [0, 1]}, dim=2))
    answer = getattr(_node(store), tool)(_INPUTS[tool])
    json.dumps(answer, allow_nan=False)
    assert isinstance(answer['success'], bool)


# ---------------------------------------------------------------------------
# Audience and the agent catalog
# ---------------------------------------------------------------------------


def _tool_methods():
    inst = object.__new__(Node)
    inst.IGlobal = SimpleNamespace(tool_description='')
    return inst, inst._collect_tool_methods()


def test_the_store_tools_are_the_six_legacy_ones_plus_the_explorer_set():
    _inst, methods = _tool_methods()
    assert set(methods) == set(LEGACY_TOOLS) | set(EXPLORER_TOOLS)


@pytest.mark.parametrize('tool', LEGACY_TOOLS)
def test_legacy_tools_stay_listed_for_agents(tool):
    _inst, methods = _tool_methods()
    assert methods[tool].__tool_meta__['audience'] == ('agent', 'dap')


@pytest.mark.parametrize('tool', EXPLORER_TOOLS)
def test_explorer_tools_are_listed_for_external_callers_only(tool):
    _inst, methods = _tool_methods()
    assert methods[tool].__tool_meta__['audience'] == ('dap',)


@pytest.mark.parametrize('tool', LEGACY_TOOLS + EXPLORER_TOOLS)
def test_every_store_tool_runs_inside_the_wrapper(tool):
    _inst, methods = _tool_methods()
    assert getattr(methods[tool], '__vectordb_tool__', False) is True


def test_the_agent_catalog_is_byte_identical_to_today():
    inst, methods = _tool_methods()
    agent = {name: m for name, m in methods.items() if 'agent' in m.__tool_meta__['audience']}
    descriptors = inst._build_tool_descriptors(dict(sorted(agent.items())))
    text = json.dumps(descriptors, sort_keys=True, separators=(',', ':'))
    assert sorted(agent) == sorted(LEGACY_TOOLS)
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == LEGACY_AGENT_CATALOG_SHA256


def test_explorer_descriptors_build_cleanly():
    inst, methods = _tool_methods()
    explorer = {name: m for name, m in methods.items() if name in EXPLORER_TOOLS}
    for descriptor in inst._build_tool_descriptors(explorer):
        assert descriptor['description'] and descriptor['inputSchema']['type'] == 'object'


def test_tool_function_records_the_audience_it_is_given():
    @tool_function(input_schema={'type': 'object'}, description='x', audience=('dap',))
    def probe(self, args):
        return {}

    assert probe.__tool_meta__['audience'] == ('dap',)
