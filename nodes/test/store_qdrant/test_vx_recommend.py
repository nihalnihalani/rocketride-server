# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Qdrant's recommendation query, as the mock server answers it.

The mock ``qdrant_client`` (``nodes/test/mocks/qdrant_client``) answers
``query_points(query=RecommendQuery(recommend=RecommendInput(...)))`` the way a
Qdrant 1.17 server does (checked against one): examples may be point ids or raw
vectors and are never returned; ``average_vector`` searches with
``avg_positive + avg_positive - avg_negative`` (``avg_positive`` without
negatives) over unit-length examples on a Cosine collection and refuses an empty
positive side; ``best_score`` scores every candidate by its best positive and
best negative similarity through Qdrant's sigmoid step and accepts negatives
alone; ``sum_scores`` sums them.
"""

from __future__ import annotations

import numpy as np
import pytest

from ._mock_driver import load_driver

drv = load_driver('_vx_qdrant_driver_mock_recommend')
Client = drv.QdrantClient
models = drv.models


@pytest.fixture(autouse=True)
def _fresh_server():
    Client.reset()
    yield
    Client.reset()


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _cos(a, b):
    return float(_unit(a) @ _unit(b))


def _sigmoid(x):
    return 0.5 * (1.0 + (x / (1.0 + abs(x))))


# ---------------------------------------------------------------------------
# The mock server
# ---------------------------------------------------------------------------


def _server(distance='Cosine', n=20, dim=5, seed=11):
    """A collection of ``n`` points with integer ids 1..n and raw (not unit) vectors."""
    client = Client(url='http://127.0.0.1:6333')
    client.create_collection('rec', vectors_config=drv.types.VectorParams(size=dim, distance=distance))
    rng = np.random.default_rng(seed)
    vectors = {i: rng.normal(size=dim) * rng.uniform(0.5, 3.0) for i in range(1, n + 1)}
    client.upsert(
        'rec',
        points=[
            drv.PointStruct(id=i, vector=v.tolist(), payload={'n': i, 'odd': i % 2 == 1}) for i, v in vectors.items()
        ],
    )
    return client, vectors


def _recommend(client, positive=None, negative=None, strategy=None, limit=50, query_filter=None):
    query = models.RecommendQuery(
        recommend=models.RecommendInput(positive=positive, negative=negative, strategy=strategy)
    )
    return client.query_points('rec', query=query, query_filter=query_filter, limit=limit).points


def test_the_mock_models_carry_the_recommendation_types():
    assert [s.value for s in models.RecommendStrategy] == ['average_vector', 'best_score', 'sum_scores']
    query = models.RecommendQuery(recommend=models.RecommendInput(positive=[1], negative=[2], strategy='best_score'))
    assert query.recommend.positive == [1] and query.recommend.negative == [2]
    assert models.RecommendInput().positive is None and models.RecommendInput().strategy is None


def test_average_vector_searches_twice_the_positive_mean_minus_the_negative_mean_over_unit_examples():
    client, vectors = _server()
    points = _recommend(client, positive=[1, 2], negative=[3], strategy='average_vector')
    avg_p = np.mean([_unit(vectors[i]) for i in (1, 2)], axis=0)
    avg_n = np.mean([_unit(vectors[3])], axis=0)
    query = avg_p + avg_p - avg_n
    expected = sorted(((_cos(query, v), i) for i, v in vectors.items() if i not in (1, 2, 3)), reverse=True)
    assert [p.id for p in points] == [i for _s, i in expected]
    assert [p.score for p in points] == pytest.approx([s for s, _i in expected])


def test_average_vector_is_the_default_strategy_and_needs_no_negative():
    client, vectors = _server()
    points = _recommend(client, positive=[4, 9])
    query = np.mean([_unit(vectors[i]) for i in (4, 9)], axis=0)
    expected = sorted(((_cos(query, v), i) for i, v in vectors.items() if i not in (4, 9)), reverse=True)
    assert [p.id for p in points] == [i for _s, i in expected]


def test_average_vector_averages_raw_vectors_on_a_dot_collection():
    client, vectors = _server(distance='Dot')
    points = _recommend(client, positive=[1, 2], negative=[3], strategy='average_vector')
    query = 2 * np.mean([vectors[1], vectors[2]], axis=0) - vectors[3]
    expected = sorted(((float(query @ v), i) for i, v in vectors.items() if i not in (1, 2, 3)), reverse=True)
    assert [p.id for p in points] == [i for _s, i in expected]


def test_average_vector_refuses_an_empty_positive_side_as_the_server_does():
    client, _vectors = _server()
    with pytest.raises(Exception, match='Positive vectors should not be empty'):
        _recommend(client, negative=[3], strategy='average_vector')


def test_best_score_follows_qdrants_step_formula():
    client, vectors = _server()
    points = _recommend(client, positive=[1, 2], negative=[3, 4], strategy='best_score')
    expected = []
    for i, v in vectors.items():
        if i in (1, 2, 3, 4):
            continue
        best_p = max(_cos(v, vectors[j]) for j in (1, 2))
        best_n = max(_cos(v, vectors[j]) for j in (3, 4))
        expected.append((_sigmoid(best_p) if best_p > best_n else -_sigmoid(best_n), i))
    expected.sort(reverse=True)
    assert [p.id for p in points] == [i for _s, i in expected]
    assert [p.score for p in points] == pytest.approx([s for s, _i in expected])


def test_best_score_with_negatives_alone_lists_the_least_similar_first():
    client, vectors = _server()
    points = _recommend(client, negative=[5], strategy=models.RecommendStrategy.BEST_SCORE)
    assert all(p.score < 0 for p in points)
    assert [p.id for p in points] == [
        i for _s, i in sorted(((-_sigmoid(_cos(v, vectors[5])), i) for i, v in vectors.items() if i != 5), reverse=True)
    ]
    assert points[0].id == min((i for i in vectors if i != 5), key=lambda i: _cos(vectors[i], vectors[5]))


def test_sum_scores_adds_positive_and_subtracts_negative_similarities():
    client, vectors = _server()
    points = _recommend(client, positive=[1], negative=[2], strategy='sum_scores')
    expected = sorted(
        ((_cos(v, vectors[1]) - _cos(v, vectors[2]), i) for i, v in vectors.items() if i not in (1, 2)), reverse=True
    )
    assert [p.id for p in points] == [i for _s, i in expected]


def test_examples_may_be_raw_vectors_and_are_never_returned():
    client, vectors = _server()
    raw = (vectors[7] * 2).tolist()
    points = _recommend(client, positive=[raw, 1], strategy='average_vector', limit=100)
    ids = [p.id for p in points]
    assert 1 not in ids and 7 in ids, 'a raw vector is not a point, so the point it copies may be returned'
    assert len(ids) == 19


def test_the_filter_selects_candidates_but_examples_are_looked_up_outside_it():
    client, _vectors = _server()
    odd = models.Filter(must=[models.FieldCondition(key='odd', match=models.MatchValue(value=True))])
    points = _recommend(client, positive=[2], strategy='best_score', query_filter=odd)
    assert points and all(p.id % 2 == 1 for p in points)


def test_an_unknown_example_id_is_refused():
    client, _vectors = _server()
    with pytest.raises(Exception, match='Not found'):
        _recommend(client, positive=[999])


def test_the_limit_and_the_call_counter():
    client, _vectors = _server()
    before = Client.calls.get('query_points', 0)
    assert len(_recommend(client, positive=[1], limit=3)) == 3
    assert Client.calls['query_points'] == before + 1
