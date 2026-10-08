# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""The committed vector wire captures (``apps/vector-ui/tests/fixtures/v1/live``) still match the tools.

The captures are regenerated live (``vector_wire_fixtures.live_fixtures``: the
engine, the shipped templates and the live test databases, as
``test_vector_toolpath_full.py`` runs them) and compared with the committed
files in their canonical form (floats to 4 decimal places, run-specific values
scrubbed). Registered as a live database suite (DB_LIVE_SUITES in
``nodes/scripts/tasks.js``); skips without the engine or the databases unless
``RR_REQUIRE_DB_TESTS`` is set.
"""

from __future__ import annotations

import json
import os

from pathlib import Path

import pytest

from . import vector_wire_fixtures as gen

FIXTURES = Path(__file__).resolve().parents[2] / 'apps' / 'vector-ui' / 'tests' / 'fixtures' / 'v1' / 'live'
_REQUIRED = bool(os.environ.get('RR_REQUIRE_DB_TESTS'))

# The captures need the explorer tools (and every supported driver) merged; the
# integration step removes this mark and commits the first capture.
NEEDS_LIVE = 'NEEDS:L0,L1,L2,L3,L5 merged — integration gate G2'


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


def test_file_names_and_differences():
    assert gen.file_name('pgvector', 'stats') == 'pgvector/stats.json'
    assert gen.file_name('qdrant', 'stats', 'quick.legacy') == 'qdrant/stats.quick.legacy.json'
    regenerated = {'a/x.json': {'v': 1.000001}, 'a/y.json': {'v': 2}}
    on_disk = {'a/x.json': gen.stored({'v': 1.0}), 'a/z.json': {}}
    assert gen.differences(regenerated, on_disk) == ['a/y.json', 'a/z.json']


# ---------------------------------------------------------------------------
# Live: regenerate and compare
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason=NEEDS_LIVE)
def test_captures_are_committed_for_every_supported_backend():
    names = set(_committed())
    for backend in ('pgvector', 'rocketride_vector', 'qdrant', 'chroma'):
        for tool in ('dialect', 'stats', 'documents', 'chunks', 'sample', 'search', 'remove_document'):
            assert gen.file_name(backend, tool) in names, f'missing {gen.file_name(backend, tool)}'
            assert gen.file_name(backend, tool, 'legacy') in names, f'missing {gen.file_name(backend, tool, "legacy")}'


@pytest.fixture(scope='module')
def live():
    try:
        return gen.live_fixtures()
    except RuntimeError as e:
        if _REQUIRED:
            pytest.fail(f'RR_REQUIRE_DB_TESTS is set but the live captures failed: {e}', pytrace=False)
        pytest.skip(f'live captures not possible here: {e}')


@pytest.mark.skip(reason=NEEDS_LIVE)
def test_the_generator_covers_every_committed_capture(live):
    assert sorted(_committed()) == sorted(live)


@pytest.mark.skip(reason=NEEDS_LIVE)
def test_live_captures_match_the_tools(live):
    diff = gen.differences(live, _committed())
    assert diff == [], (
        f'apps/vector-ui/tests/fixtures/v1/live: {diff} no longer match the tools; regenerate them '
        '(see nodes/test/vector_wire_fixtures.py)'
    )
