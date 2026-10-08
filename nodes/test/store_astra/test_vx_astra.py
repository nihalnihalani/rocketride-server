# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Astra DB driver repairs bundled with the Vector Explorer hooks (mocked client).

The shared hook contract is in ``nodes/test/test_vector_other_drivers.py``;
these tests pin what is specific to Astra: counts with the required
``upper_bound``, the metadata written (control-record extras kept, other extras
and nulls dropped), rows written with nulls still read, ``get`` paging with a
sort, and ``describe`` from the collection definition.
"""

import pytest

from ai.common.schema import DocFilter

from .. import vector_other_drivers_harness as h


@pytest.fixture(scope='module')
def adapter():
    """Astra driver loaded against the astrapy mock."""
    return h.AstraAdapter()


@pytest.fixture
def store(adapter):
    """A fresh store on an empty mock database."""
    return adapter.new_store()


def test_count_documents_passes_an_upper_bound(adapter, store):
    """Astrapy 2 requires upper_bound; past it the estimated count answers."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0, 1, 2])
    assert store.count_documents() == 4
    adapter.module.COUNT_UPPER_BOUND, saved = 2, adapter.module.COUNT_UPPER_BOUND
    try:
        assert store.count_documents() == 4
        assert store.countChunks(DocFilter()) is None
    finally:
        adapter.module.COUNT_UPPER_BOUND = saved


def test_metadata_keeps_the_control_extras_and_drops_nulls(adapter, store):
    """The control record keeps vectorSize/modelName; chunks keep declared fields only, never nulls."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0])
    rows = {r['objectId']: r['meta'] for r in adapter.raw_rows(store)}
    assert rows['schema']['vectorSize'] == h.DIM
    assert rows['schema']['modelName'] == h.MODEL
    assert 'size' not in rows['doc-a'] and 'ingestedAt' not in rows['doc-a']
    for meta in rows.values():
        assert None not in meta.values()


def test_rows_written_with_nulls_are_still_read(adapter, store):
    """Older rows hold explicit nulls; reading them does not fail validation."""
    adapter.seed_legacy(store)
    docs = store.get(DocFilter(objectIds=['legacy-a'], limit=10))
    assert sorted(doc.metadata.chunkId for doc in docs) == [0, 1, 2]


def test_get_honours_the_offset(store):
    """Get pages with skip (and the sort skip needs) instead of returning the first page again."""
    for i in range(5):
        h.ingest(store, f'doc-{i}', f'/docs/{i}.md', [0])
    first = store.get(DocFilter(chunkIds=[0], limit=2))
    second = store.get(DocFilter(chunkIds=[0], limit=2, offset=2))
    assert len(first) == 2 and len(second) == 2
    assert {d.metadata.objectId for d in first}.isdisjoint({d.metadata.objectId for d in second})


def test_describe_reads_the_collection_definition(store):
    """Dimension and metric come from the definition; the endpoint is never reported."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0])
    info = store.describe()
    assert info.dimension == h.DIM
    assert info.metric == 'cosine'
    assert info.index['type'] == 'vector'
    assert {'experimental', 'cloud_only_unverified', 'extras_not_stored'} <= set(info.caveats)
    assert 'example.invalid' not in repr(info)
