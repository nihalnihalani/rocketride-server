# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Weaviate driver repairs bundled with the Vector Explorer hooks (mocked client).

The shared hook contract is in ``nodes/test/test_vector_other_drivers.py``;
these tests pin what is specific to Weaviate: the score scale per distance
metric, ids keyed by (objectId, chunkId), paging by offset in ``get``,
keyword search on the question text, group-by document counts and
``describe``'s index details.
"""

import pytest

from ai.common.schema import DocFilter, QuestionText

from .. import vector_other_drivers_harness as h


@pytest.fixture(scope='module')
def adapter():
    """Weaviate driver loaded against the weaviate mock."""
    return h.WeaviateAdapter()


@pytest.fixture
def store(adapter):
    """A fresh store on an empty mock server."""
    return adapter.new_store()


def _query(vector):
    return QuestionText(text='q', embedding=vector, embedding_model=h.MODEL)


def test_cosine_scores_rank_the_identical_vector_first(store):
    """Cosine distance d scores (2 - d) / 2: an identical vector scores 1.0, not 0.5."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0])
    h.ingest(store, 'doc-b', '/docs/b.md', [0])
    docs = store.searchSemantic(_query(h.vector_for('doc-a', 0)), DocFilter())
    assert docs[0].metadata.objectId == 'doc-a'
    assert docs[0].score == pytest.approx(1.0)
    assert all(doc.score <= docs[0].score for doc in docs)


@pytest.mark.parametrize(
    ('metric', 'distance', 'score'),
    [('dot', -0.8, 0.8), ('l2-squared', 3.0, 0.25), ('manhattan', 1.0, 0.5)],
)
def test_other_metrics_score_higher_when_closer(adapter, store, metric, distance, score):
    """Dot distance is the negative dot product; l2-squared and manhattan score 1 / (1 + d)."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0])
    store.similarity = store.similarityDict[metric]
    obj_id, obj = next((uid, o) for uid, o in adapter.storage(store).items() if o['properties']['objectId'] == 'doc-a')
    mock = adapter.mock

    def near_vector(*args, **kwargs):
        props = {k: v for k, v in obj['properties'].items() if v is not None}
        return mock.QueryResult(
            objects=[mock.QueryObject(uuid=obj_id, properties=props, metadata=mock.MetadataResult(distance=distance))]
        )

    store.collectionObj.query.near_vector = near_vector
    docs = store.searchSemantic(_query(h.vector_for('q', 0)), h.VxFilter(minScore=float('-inf')))
    assert [doc.score for doc in docs] == pytest.approx([score])


def test_objects_are_keyed_by_object_and_chunk(adapter, store):
    """New writes use uuid5('<objectId>#<chunkId>'), so a key maps to one object."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0, 1])
    ids = {o['properties']['objectId']: [] for o in adapter.storage(store).values()}
    for uid, obj in adapter.storage(store).items():
        ids[obj['properties']['objectId']].append(uid)
    assert sorted(ids['doc-a']) == sorted(h.keyed_uuid('doc-a', c) for c in (0, 1))
    assert ids['schema'] == [h.keyed_uuid('schema', 0)]


def test_get_honours_the_offset(store):
    """Get pages with offset instead of returning the first page again."""
    for i in range(5):
        h.ingest(store, f'doc-{i}', f'/docs/{i}.md', [0])
    first = store.get(DocFilter(chunkIds=[0], limit=2))
    second = store.get(DocFilter(chunkIds=[0], limit=2, offset=2))
    assert len(first) == 2 and len(second) == 2
    assert {d.metadata.objectId for d in first}.isdisjoint({d.metadata.objectId for d in second})


def test_keyword_search_matches_the_question_text(store):
    """The keyword pattern is built from the question text, not the model's repr."""
    h.ingest(store, 'doc-a', '/geo/Paris.md', [0])
    h.ingest(store, 'doc-b', '/geo/Rome.md', [0])
    found = store.searchKeyword(_query(h.vector_for('q', 0)).model_copy(update={'text': 'Paris'}), DocFilter())
    assert [doc.metadata.objectId for doc in found] == ['doc-a']


def test_count_documents_groups_by_object(adapter, store):
    """Documents are counted natively (group by objectId), a document without chunk 0 included."""
    adapter.seed_legacy(store)
    assert store.countDocuments(h.VxFilter(deleted='active')) == 3
    assert 'countDocuments' in store.capabilities()


def test_describe_reports_the_index_and_version(store):
    """The description carries the HNSW index and the server version, never the host."""
    h.ingest(store, 'doc-a', '/docs/a.md', [0])
    info = store.describe()
    assert info.index['type'] == 'hnsw'
    assert info.backend_version == '1.30.0-mock'
    assert 'score_scale_inverted_fixed' in info.caveats
    assert '8080' not in repr(info) and 'localhost' not in repr(info)
