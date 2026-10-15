# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""The frozen shapes of the vector store contract's additive extensions (section 4.4).

What every store node reports or accepts before any of the new tools or fields
is implemented, so the app and the drivers can build against it:

* the new vocabulary entries (capability keys, caveats, the value lists of the
  new answer fields) and the three new limits, reported in ``dialect.limits``;
* ``dialect.capabilities`` names every new key: ``clusters`` is false until the
  node computes clusters, ``documents_filter`` and ``recommend_best_score`` follow
  the driver's ``VX_DRIVER_CAPABILITIES``;
* ``parse_doc_list_filter``: the ``documents`` filter, normalised, and every input
  it refuses with a sentence;
* ``VectorExplorerExtTools`` is mixed in ahead of ``VectorExplorerTools`` without
  an import cycle, and the agent catalog is unchanged (pinned by
  ``test_vector_tool_envelope``).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from ai.common.store import VectorExplorerExtTools, VectorExplorerTools, VectorStoreToolMixin
from ai.common.store import vx_tools, vx_tools_ext, vx_types
from ai.common.store.vx_defaults import VECTOR_TOOL_LIMITS
from ai.common.store.vx_types import DocListFilter, parse_doc_list_filter

from .test_vector_hooks import MemoryStore, corpus
from .test_vectordb_tool_mixin import node

# ---------------------------------------------------------------------------
# Vocabularies and limits
# ---------------------------------------------------------------------------


def test_the_new_capability_keys_and_caveats_are_appended_to_the_vocabularies():
    assert vx_types.CAPABILITY_KEYS[-3:] == ('clusters', 'documents_filter', 'recommend_best_score')
    assert vx_types.CAVEATS[-3:] == ('listing_truncated', 'documents_filter_partial', 'documents_filter_client')
    for vocabulary in (vx_types.CAPABILITY_KEYS, vx_types.CAVEATS):
        assert len(set(vocabulary)) == len(vocabulary)


def test_the_value_lists_of_the_new_answer_fields():
    assert vx_types.FILTER_APPLIED_VALUES == ('server', 'partial', 'none')
    assert vx_types.LISTING_REASONS == ('complete', 'cap', 'stale', 'pages', 'budget')
    assert vx_types.CLUSTER_METHODS == ('knn-components',)
    assert vx_types.CLUSTER_LABEL_SOURCES == ('text', 'paths')
    assert vx_types.RECOMMEND_STRATEGIES == ('average_vector', 'best_score')
    assert vx_types.MATRIX_SOURCES == ('cache', 'store', 'mixed')
    assert vx_types.KEYWORD_MATCHES == ('substring', 'token')


def test_the_new_limits_and_their_values():
    assert VECTOR_TOOL_LIMITS['recommend_examples_max'] == 10
    assert VECTOR_TOOL_LIMITS['matrix_keys_max'] == 100
    assert VECTOR_TOOL_LIMITS['max_components'] == 200
    # The first contract's limits are unchanged, in their order, ahead of the new ones.
    assert list(VECTOR_TOOL_LIMITS)[-3:] == ['recommend_examples_max', 'matrix_keys_max', 'max_components']


def test_dialect_reports_the_new_limits():
    limits = node(MemoryStore().seed(corpus({'a': [0]}))).dialect({})['limits']
    assert limits['recommend_examples_max'] == 10 and limits['matrix_keys_max'] == 100
    assert limits['max_components'] == 200


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class _FilteringStore(MemoryStore):
    """A driver that says it filters listings and recommends natively."""

    VX_DRIVER_CAPABILITIES = frozenset({'documents_filter', 'recommend_best_score'})


def test_dialect_names_every_capability_key_and_the_new_ones_are_off_by_default():
    caps = node(MemoryStore().seed(corpus({'a': [0]}))).dialect({})['capabilities']
    assert set(vx_types.CAPABILITY_KEYS) - {'embed_node'} <= set(caps)
    assert caps['clusters'] is False
    assert caps['documents_filter'] is False
    assert caps['recommend_best_score'] is False


def test_the_driver_declares_documents_filter_and_recommend_best_score():
    caps = node(_FilteringStore().seed(corpus({'a': [0]}))).dialect({})['capabilities']
    assert caps['documents_filter'] is True and caps['recommend_best_score'] is True
    assert caps['clusters'] is False, 'clusters is the node, not the driver'


# ---------------------------------------------------------------------------
# The documents filter
# ---------------------------------------------------------------------------


def test_the_filter_of_the_contract_example_is_read_as_given():
    parsed = parse_doc_list_filter(
        {
            'path_prefix': 'C:/demo/handbooks/',
            'file_types': ['md', 'pdf'],
            'ingested_after': '2026-10-01T00:00:00Z',
            'ingested_before': None,
            'min_chunks': 1,
            'max_chunks': None,
            'has_first_chunk': True,
            'has_tables': None,
            'path_contains': None,
        }
    )
    assert parsed == DocListFilter(
        path_prefix='C:/demo/handbooks/',
        file_types=('md', 'pdf'),
        ingested_after='2026-10-01T00:00:00Z',
        min_chunks=1,
        has_first_chunk=True,
    )
    assert parsed.given() == ('path_prefix', 'file_types', 'ingested_after', 'min_chunks', 'has_first_chunk')


def test_the_filter_is_frozen_and_keyed_as_documented():
    assert tuple(f.name for f in dataclasses.fields(DocListFilter)) == vx_types.DOC_LIST_FILTER_KEYS
    with pytest.raises(dataclasses.FrozenInstanceError):
        DocListFilter().path_prefix = 'x'  # type: ignore[misc]


@pytest.mark.parametrize('value', [None, {}, {'path_prefix': None, 'file_types': []}, {'path_contains': ''}])
def test_a_filter_that_sets_nothing_is_none(value):
    assert parse_doc_list_filter(value) is None


@pytest.mark.parametrize(
    'given,expected',
    [
        ('2026-10-01', '2026-10-01T00:00:00Z'),
        ('2026-10-01T12:30:00', '2026-10-01T12:30:00Z'),
        ('2026-10-01T12:30:00z', '2026-10-01T12:30:00Z'),
        ('2026-10-01T14:30:00+02:00', '2026-10-01T12:30:00Z'),
        ('2026-10-01T12:30:00.750Z', '2026-10-01T12:30:00Z'),
        ('2026-10-01T12:30-05:30', '2026-10-01T18:00:00Z'),
        (' 2026-10-01 12:30:00Z ', '2026-10-01T12:30:00Z'),
    ],
)
def test_dates_become_utc_in_the_stored_form(given, expected):
    # The stored ingestedAt is UTC 'YYYY-MM-DDTHH:MM:SSZ', so the bounds compare with it as text.
    assert parse_doc_list_filter({'ingested_after': given}).ingested_after == expected
    assert parse_doc_list_filter({'ingested_before': given}).ingested_before == expected


def test_file_types_are_lower_cased_without_the_dot_and_without_repeats():
    assert parse_doc_list_filter({'file_types': ['.PDF', 'md', ' Md ', 'pdf']}).file_types == ('pdf', 'md')


def test_text_up_to_the_limit_is_kept_as_given():
    prefix = 'C:\\Users\\' + 'x' * (vx_types.DOC_LIST_FILTER_TEXT_MAX - 9)
    assert len(prefix) == vx_types.DOC_LIST_FILTER_TEXT_MAX
    assert parse_doc_list_filter({'path_prefix': prefix, 'path_contains': '%_'}) == DocListFilter(
        path_prefix=prefix, path_contains='%_'
    )


def test_min_chunks_may_equal_max_chunks():
    assert parse_doc_list_filter({'min_chunks': 3, 'max_chunks': 3.0}) == DocListFilter(min_chunks=3, max_chunks=3)


@pytest.mark.parametrize(
    'value,sentence',
    [
        ('C:/demo', 'filter must be an object'),
        (['path_prefix'], 'filter must be an object'),
        ({'folder': 'C:/demo', 'deleted': 'all'}, 'unknown keys: deleted, folder'),
        ({'path_prefix': 7}, 'filter.path_prefix must be text'),
        ({'path_contains': 'x' * 1025}, 'at most 1024 characters'),
        ({'path_prefix': 'x' * 1025}, 'at most 1024 characters'),
        ({'ingested_after': '1 October 2026'}, 'ISO-8601'),
        ({'ingested_before': '2026-13-01'}, 'ISO-8601'),
        ({'ingested_after': 20261001}, 'ISO-8601'),
        ({'ingested_after': '20261001'}, 'ISO-8601'),
        ({'ingested_after': '2026-02-30'}, 'ISO-8601'),
        ({'ingested_after': '2026-10-01T24:00:00Z'}, 'ISO-8601'),
        ({'ingested_after': '2026-10-01T00:00:00+25:00'}, 'ISO-8601'),
        ({'ingested_after': '2026-10-01T00:00:00 UTC'}, 'ISO-8601'),
        ({'ingested_after': '  '}, 'ISO-8601'),
        ({'min_chunks': -1}, 'whole number'),
        ({'max_chunks': 2.5}, 'whole number'),
        ({'min_chunks': True}, 'whole number'),
        ({'max_chunks': '3'}, 'whole number'),
        ({'min_chunks': 5, 'max_chunks': 2}, 'min_chunks must not be greater than'),
        ({'has_tables': 'yes'}, 'true, false or null'),
        ({'has_first_chunk': 0}, 'true, false or null'),
        ({'file_types': 'md'}, 'list of at most'),
        ({'file_types': ['md'] * 33}, 'list of at most 32'),
        ({'file_types': ['tar.gz']}, 'extensions such as'),
        ({'file_types': ['']}, 'extensions such as'),
        ({'file_types': [3]}, 'extensions such as'),
    ],
)
def test_every_refused_filter_says_why(value, sentence):
    with pytest.raises(ValueError, match=sentence.replace('(', r'\(').replace('.', r'\.')):
        parse_doc_list_filter(value)


# ---------------------------------------------------------------------------
# The additive tools' class
# ---------------------------------------------------------------------------


def test_the_additive_tools_are_mixed_in_ahead_of_the_explorer_tools():
    mro = VectorStoreToolMixin.__mro__
    assert mro.index(VectorExplorerExtTools) < mro.index(VectorExplorerTools)
    assert vx_tools_ext.VectorExplorerExtTools is VectorExplorerExtTools


def test_vx_tools_never_imports_the_additive_module():
    source = Path(vx_tools.__file__).read_text(encoding='utf-8')
    imported = {node.module or '' for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not [name for name in imported if name.endswith('vx_tools_ext')]


def test_every_tool_on_the_additive_class_is_external_only_and_wrapped():
    tools = {
        name: value
        for name, value in vars(VectorExplorerExtTools).items()
        if callable(value) and hasattr(value, '__tool_meta__')
    }
    for name, method in tools.items():
        assert method.__tool_meta__['audience'] == ('dap',), name
        assert getattr(method, '__vectordb_tool__', False) is True, name
