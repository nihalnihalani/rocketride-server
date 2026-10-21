# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""The committed vector wire captures (``apps/vector-ui/tests/fixtures/v1/live``) still match the tools.

The captures are regenerated live (``vector_wire_fixtures.live_fixtures``: the
engine, the shipped templates and the live test databases, as
``test_vector_toolpath_full.py`` runs them) and compared with the committed
files in their canonical form (floats to 4 decimal places, run-specific values
scrubbed; the floats of embedding-derived answers within
``FLOAT_TOLERANCE``). A tool answering a capture with another outcome than the
one it is for fails generation. Registered as a live database suite
(DB_LIVE_SUITES in ``nodes/scripts/tasks.js``); skips without the engine or the
databases unless ``RR_REQUIRE_DB_TESTS`` is set, and never runs under
``ROCKETRIDE_MOCK`` (NOT RUN).
"""

from __future__ import annotations

import json
import os

from pathlib import Path
from types import SimpleNamespace

import pytest

from . import vector_wire_fixtures as gen

FIXTURES = Path(__file__).resolve().parents[2] / 'apps' / 'vector-ui' / 'tests' / 'fixtures' / 'v1' / 'live'
_REQUIRED = bool(os.environ.get('RR_REQUIRE_DB_TESTS'))


def _committed():
    return gen.committed(FIXTURES) if FIXTURES.is_dir() else {}


# ---------------------------------------------------------------------------
# The canonical form (no engine needed)
# ---------------------------------------------------------------------------


def test_canonical_form_rounds_floats_and_scrubs_run_specific_values():
    answer = {
        'success': True,
        'score': 0.123456789,
        'tiny': -0.00001,
        'computed_at': '2026-10-08T18:31:03Z',
        'items': [{'pointId': 'a3f', 'sim': 0.987654321, 'objectId': '060f'}],
        'caller': {'auth': 'account', 'userId': 'u-1', 'teamId': None},
    }
    out = gen.stored(answer)
    assert out['__scrub__'] == ['computed_at', 'pointId', 'userId']
    assert out['score'] == 0.1235 and out['tiny'] == 0.0
    assert out['computed_at'] == gen.SCRUBBED and out['items'][0]['pointId'] == gen.SCRUBBED
    assert out['items'][0]['objectId'] == '060f' and out['items'][0]['sim'] == 0.9877
    assert out['caller'] == {'auth': 'account', 'userId': gen.SCRUBBED, 'teamId': None}


def test_canonical_form_ignores_only_run_specific_values():
    a = {'took_ms': 12, 'ingestedAt': '2026-01-01', 'path': 'C:/demo/a.md', 'values': [0.11111111, 0.2]}
    b = {'took_ms': 99, 'ingestedAt': '2027-01-01', 'path': 'C:/demo/a.md', 'values': [0.11111119, 0.2]}
    assert gen.stored(a) == gen.stored(b)
    changed = dict(b, path='C:/demo/b.md')
    assert gen.stored(a) != gen.stored(changed)
    assert gen.stored(a) != gen.stored(dict(b, values=[0.1112, 0.2]))


def test_stored_form_is_idempotent_and_valid_json():
    once = gen.stored({'x': 1.234567, 'computed_at': 'now', 'nan': float('nan')})
    assert gen.stored(once) == once
    json.dumps(once, allow_nan=False)


def test_opaque_cursors_and_sample_ids_are_scrubbed_but_their_absence_is_kept():
    out = gen.stored({'items': [], 'next_cursor': 'eyJvIjoyfQ', 'sample_id': 's-7-a1b2c3d4'})
    assert out['next_cursor'] == gen.SCRUBBED and out['sample_id'] == gen.SCRUBBED
    # The end of a listing (no cursor) is part of the answer.
    assert gen.stored({'items': [], 'next_cursor': None})['next_cursor'] is None


def test_an_unsorted_documents_page_compares_as_a_set_of_documents():
    a = {'objectId': 'a', 'path': 'C:/demo/a.md', 'chunks': 2}
    b = {'objectId': 'b', 'path': 'C:/demo/b.md', 'chunks': 1}
    on_disk = {'qdrant/documents.legacy.json': gen.stored({'items': [a, b], 'sorted': False})}
    # A backend that lists in storage order may return the same page in another order.
    assert gen.differences({'qdrant/documents.legacy.json': {'items': [b, a], 'sorted': False}}, on_disk) == []
    # Another page, or a sorted listing in another order, is a difference.
    c = dict(b, objectId='c')
    assert gen.differences({'qdrant/documents.legacy.json': {'items': [c, a], 'sorted': False}}, on_disk) == [
        'qdrant/documents.legacy.json'
    ]
    sorted_disk = {'pgvector/documents.json': gen.stored({'items': [a, b], 'sorted': True})}
    assert gen.differences({'pgvector/documents.json': {'items': [b, a], 'sorted': True}}, sorted_disk) == [
        'pgvector/documents.json'
    ]


def test_file_names_and_differences():
    assert gen.file_name('pgvector', 'stats') == 'pgvector/stats.json'
    assert gen.file_name('qdrant', 'stats', 'quick.legacy') == 'qdrant/stats.quick.legacy.json'
    regenerated = {'a/x.json': {'v': 1.000001}, 'a/y.json': {'v': 2}}
    on_disk = {'a/x.json': gen.stored({'v': 1.0}), 'a/z.json': {}}
    assert gen.differences(regenerated, on_disk) == ['a/y.json', 'a/z.json']


def test_similarity_answers_compare_within_a_tolerance_and_the_rest_exactly():
    sample = {'success': True, 'n': 2, 'points': {'x': [0.1234, -0.5], 'doc': [0, 1]}, 'knn': {'sims': [0.91, 0.88]}}
    nearby = {
        'success': True,
        'n': 2,
        'points': {'x': [0.1237, -0.5003], 'doc': [0, 1]},
        'knn': {'sims': [0.9104, 0.88]},
    }
    on_disk = {'qdrant/sample.json': gen.stored(sample), 'qdrant/stats.json': gen.stored({'avg_chunks': 0.5})}
    # Another CPU's BLAS moves the last digits of similarity-derived floats: not a difference.
    assert gen.differences({'qdrant/sample.json': nearby, 'qdrant/stats.json': {'avg_chunks': 0.5}}, on_disk) == []
    # Beyond the tolerance, or anything that is not a float, is.
    far = dict(nearby, points={'x': [0.1334, -0.5], 'doc': [0, 1]})
    assert gen.differences({'qdrant/sample.json': far, 'qdrant/stats.json': {'avg_chunks': 0.5}}, on_disk) == [
        'qdrant/sample.json'
    ]
    moved = dict(nearby, points={'x': [0.1234, -0.5], 'doc': [1, 0]})
    assert gen.differences({'qdrant/sample.json': moved, 'qdrant/stats.json': {'avg_chunks': 0.5}}, on_disk) == [
        'qdrant/sample.json'
    ]
    extra = dict(nearby, extra=True)
    assert gen.differences({'qdrant/sample.json': extra, 'qdrant/stats.json': {'avg_chunks': 0.5}}, on_disk) == [
        'qdrant/sample.json'
    ]
    # Exact answers (stats, documents, refusals, ...) stay exact.
    assert gen.differences({'qdrant/sample.json': sample, 'qdrant/stats.json': {'avg_chunks': 0.5003}}, on_disk) == [
        'qdrant/stats.json'
    ]


def test_an_answer_with_another_outcome_than_expected_is_reported():
    assert gen.outcome_problem({'success': True, 'items': []}, gen.OK) is None
    assert gen.outcome_problem({'results': [], 'total': 0}, gen.OK) is None  # the legacy search answer has no success
    assert gen.outcome_problem({'success': False, 'code': 'WRITES_SOURCE'}, 'WRITES_SOURCE') is None
    assert gen.outcome_problem({'success': False, 'code': 'NOT_FOUND', 'error': 'x'}, gen.OK)
    assert gen.outcome_problem({'success': True, 'removed': {'chunks': 3}}, 'WRITES_SOURCE')
    assert gen.outcome_problem({'success': False, 'code': 'WRITES_DISABLED'}, 'WRITES_SOURCE')
    assert gen.outcome_problem(None, gen.OK)


class _FakeSide:
    """Answers every call as the tools should, except the outcomes overridden by (tool, input key)."""

    def __init__(self, wrong=None):
        self.calls = []
        self.wrong = wrong or {}

    def tool(self, name, inp=None, *, source='tools_1', node='store_1'):
        inp = inp or {}
        self.calls.append((name, inp, source, node))
        key = (name, source, node)
        if key in self.wrong:
            return self.wrong[key]
        if name == 'chunks' and inp.get('object_id') == 'schema':
            return {'success': False, 'code': 'NOT_FOUND', 'error': 'no such document'}
        if name == 'search' and len(inp.get('vector') or []) == 10:
            return {'success': False, 'code': 'DIMENSION_MISMATCH', 'error': 'dimension'}
        if name == 'remove_document':
            if inp.get('object_ids') == ['schema']:
                return {'success': False, 'code': 'RESERVED_ID', 'error': 'control record'}
            if source != 'tools_1':
                return {'success': False, 'code': 'WRITES_SOURCE', 'error': 'source'}
            if node != 'store_1':
                return {'success': False, 'code': 'WRITES_DISABLED', 'error': 'switch'}
        if name == 'sample':
            return {'success': True, 'sample_id': 's-7-0000aaaa', 'n': 12, 'of': {'chunks': 12, 'documents': 8}}
        return {'success': True}


_TP = SimpleNamespace(object_id=lambda name: f'oid:{name}')


def test_every_capture_states_its_expected_outcome_and_writes_go_last():
    side = _FakeSide()
    out = gen._captures_for(_TP, side, 'new', 'qdrant', 'multi', [0.1] * 384, [0.2] * 384)
    assert out and all(name.startswith('qdrant/') for name in out)
    names = [c[0] for c in side.calls]
    first_write = names.index('remove_document')
    assert set(names[first_write:]) == {'remove_document'}, 'every refused write comes after the reads'
    # A refused write that the gate wrongly let through must not remove a real document.
    for name, inp, source, node in side.calls:
        if name == 'remove_document' and (source, node) != ('tools_1', 'store_1'):
            assert inp['object_ids'] == [gen.disposable_id(_TP)], (source, node, inp)


def test_generation_fails_when_a_refusal_is_answered_as_success():
    side = _FakeSide(wrong={('remove_document', 'chat_1', 'store_1'): {'success': True, 'removed': {'chunks': 0}}})
    with pytest.raises(gen.CaptureMismatch, match='remove_document.writes_source'):
        gen._captures_for(_TP, side, 'new', 'qdrant', 'multi', [0.1] * 384, [0.2] * 384)


def test_a_wire_sample_must_hold_every_chunk_so_its_capture_is_reproducible():
    side = _FakeSide()
    gen._captures_for(_TP, side, 'new', 'qdrant', 'multi', [0.1] * 384, [0.2] * 384)
    asked = [inp['n'] for name, inp, _, _ in side.calls if name == 'sample']
    assert asked and all(n == gen.WIRE_SAMPLE_N for n in asked)
    # A backend that fills a partial sample at random (Qdrant's native RANDOM) answers differently each run.
    partial = {'success': True, 'sample_id': 's-7-0000bbbb', 'n': 40, 'of': {'chunks': 80, 'documents': 8}}
    with pytest.raises(gen.CaptureMismatch, match='sample'):
        gen._captures_for(
            _TP, _FakeSide(wrong={('sample', 'tools_1', 'store_1'): partial}), 'new', 'qdrant', 'multi', [0.1], [0.2]
        )


def test_every_required_capture_is_generated_for_both_sides():
    new, legacy = _FakeSide(), _FakeSide()
    out = gen._backend_captures(_TP, new, legacy, 'qdrant', 'multi', 'second', [0.1] * 384, [0.2] * 384)
    missing = sorted(set(gen.required_captures('qdrant')) - set(out))
    assert missing == [], f'the coverage test demands captures the generator never writes: {missing}'
    # Each side removes a document of its own last, after every read of that side.
    for side in (new, legacy):
        removal = [
            i for i, c in enumerate(side.calls) if c[0] == 'remove_document' and c[1] == {'object_ids': ['second']}
        ]
        assert removal == [len(side.calls) - 1], side.calls[-3:]


def test_a_live_suite_does_not_run_under_mocks(monkeypatch):
    monkeypatch.setenv('ROCKETRIDE_MOCK', '/somewhere/mocks')
    assert gen.live_blocker().startswith('NOT RUN: ')
    monkeypatch.delenv('ROCKETRIDE_MOCK')
    assert gen.live_blocker() is None


# ---------------------------------------------------------------------------
# Live: regenerate and compare
# ---------------------------------------------------------------------------


def test_captures_are_committed_for_every_supported_backend():
    names = set(_committed())
    for backend in ('pgvector', 'rocketride_vector', 'qdrant', 'chroma'):
        missing = sorted(set(gen.required_captures(backend)) - names)
        assert missing == [], f'missing {missing}'


@pytest.fixture(scope='module')
def live():
    blocker = gen.live_blocker()
    if blocker:
        pytest.skip(blocker)
    try:
        return gen.live_fixtures()
    except RuntimeError as e:
        if _REQUIRED:
            pytest.fail(f'RR_REQUIRE_DB_TESTS is set but the live captures failed: {e}', pytrace=False)
        pytest.skip(f'NOT RUN: live captures not possible here: {e}')


def test_the_generator_covers_every_committed_capture(live):
    assert sorted(_committed()) == sorted(live)


def test_live_captures_match_the_tools(live):
    diff = gen.differences(live, _committed())
    assert diff == [], (
        f'apps/vector-ui/tests/fixtures/v1/live: {diff} no longer match the tools; regenerate them '
        '(see nodes/test/vector_wire_fixtures.py)'
    )
