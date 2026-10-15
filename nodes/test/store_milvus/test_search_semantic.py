"""
Tests for Milvus Store.searchSemantic score filtering.

The driver drops hits below its score floor (``scoreInfo()['floor']``, lifted by
``DocFilter.minScore``); the node's ``score`` threshold is applied by the data
lane (``DocumentStoreBase._queryDocuments``), not twice in the driver.
"""

import math

import pytest

from ai.common.schema import DocFilter, QuestionText

from .. import vector_other_drivers_harness as h


@pytest.fixture(scope='module')
def adapter():
    """Milvus driver loaded against the pymilvus mock."""
    return h.MilvusAdapter()


@pytest.fixture
def store(adapter):
    """A store holding four chunks."""
    store = adapter.new_store()
    h.ingest(store, 'doc-a', '/docs/a.md', [0, 1, 2, 3])
    return store


def _search(store, doc_filter):
    query = QuestionText(text='q', embedding=h.vector_for('q', 0), embedding_model=h.MODEL)
    return [doc.score for doc in store.searchSemantic(query, doc_filter)]


def test_hits_below_the_floor_are_dropped(adapter, store):
    """0.1 is under the 0.2 floor; 0.3 is kept although it is under the 0.5 threshold."""
    adapter.set_scores(store, [0.6, 0.1, 0.8, 0.3])
    assert _search(store, DocFilter()) == pytest.approx([0.6, 0.8, 0.3])


def test_exact_floor_is_included(adapter, store):
    """A hit scoring exactly the floor is kept."""
    adapter.set_scores(store, [0.2])
    assert _search(store, DocFilter()) == pytest.approx([0.2])


def test_min_score_minus_infinity_keeps_every_hit(adapter, store):
    """The explorer's neighbours view asks for every row."""
    adapter.set_scores(store, [0.6, 0.05, 0.0])
    assert _search(store, h.VxFilter(minScore=-math.inf)) == pytest.approx([0.6, 0.05, 0.0])


def test_the_threshold_is_not_applied_by_the_driver(adapter, store):
    """Raising the node threshold does not change what the driver returns."""
    store.threshold_search = 0.9
    adapter.set_scores(store, [0.6, 0.7])
    assert _search(store, DocFilter()) == pytest.approx([0.6, 0.7])
