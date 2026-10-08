# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Live wire captures of the vector store tools for vector-ui's tests (``apps/vector-ui/tests/fixtures/v1/live``).

The app's unit tests run on these answers, so its parsing is pinned to what
the tools really return, not to a hand-written guess. Each capture is one tool
answer from a template started in a real engine (the machinery of
``test_vector_toolpath_full.py``: no mocks, the broker stand-in, the LLM test
stub), on a new collection and on a legacy-shaped copy of it, written to
``<out>/<backend>/<tool>[.<case>].json``.

Answers are stored in a canonical form so a capture is stable across runs and
machines: floats are rounded to 4 decimal places, and the values of the keys in
``SCRUB_KEYS`` (times, durations, point ids, caller ids, sizes) are replaced by
``"<scrubbed>"``; every file lists the keys it scrubbed in ``__scrub__``. The
upload names are fixed (``C:/demo/<folder>/<file>``), so objectIds are too.

``test_vector_wire_fixtures_full.py`` regenerates the captures and compares
them with the committed files. To regenerate, from ``nodes/`` (unmocked, with
the live test databases up)::

    ../dist/server/engine test/vector_wire_fixtures.py ../apps/vector-ui/tests/fixtures/v1/live [--only qdrant,chroma]
"""

from __future__ import annotations

import json
import math
import os
import sys

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCRUB_KEYS = frozenset(
    {
        'computed_at',
        'counts_as_of',
        'ingestedAt',
        'modifyTime',
        'took_ms',
        'ms',
        'pointId',
        'expires_in_s',
        'size_bytes',
        'userId',
        'teamId',
        'orgId',
        'backend_version',
        'retry_after_s',
    }
)
SCRUBBED = '<scrubbed>'
FLOAT_DIGITS = 4

# Fixed names, so the objectIds in the captures are the same on every run.
WIRE_PREFIX = 'C:/demo/'
WIRE_COLLECTION = 'vx_tp_wire'
WIRE_LEGACY = 'vx_tp_wire_legacy'


def canonical(value: Any, scrubbed: Optional[set] = None) -> Any:
    """The stable form of an answer: floats rounded, run-specific values replaced (keys collected in scrubbed)."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == '__scrub__':
                continue
            if key in SCRUB_KEYS and item is not None:
                if scrubbed is not None:
                    scrubbed.add(key)
                out[key] = SCRUBBED
            else:
                out[key] = canonical(item, scrubbed)
        return out
    if isinstance(value, list):
        return [canonical(item, scrubbed) for item in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        rounded = round(value, FLOAT_DIGITS)
        return 0.0 if rounded == 0 else rounded
    return value


def stored(value: Any) -> Any:
    """The committed form: canonical, plus the sorted list of keys it scrubbed."""
    scrubbed: set = set()
    out = canonical(value, scrubbed)
    if isinstance(out, dict):
        out = {'__scrub__': sorted(scrubbed), **out}
    return out


def file_name(backend: str, tool: str, case: Optional[str] = None) -> str:
    """``<backend>/<tool>[.<case>].json``."""
    return f'{backend}/{tool}{"." + case if case else ""}.json'


def _write(out_dir: Path, captures: Dict[str, Any]) -> None:
    for name, value in sorted(captures.items()):
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(stored(value), indent=2, allow_nan=False) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Live capture (needs the engine, the test databases and the explorer tools)
# ---------------------------------------------------------------------------


def _captures_for(
    tp, deployment_side, kind: str, backend: str, multi: str, water: List[float], unrelated: List[float]
) -> Dict[str, Any]:
    side = deployment_side
    case = (lambda c: c) if kind == 'new' else (lambda c: f'{c}.legacy' if c else 'legacy')
    out: Dict[str, Any] = {}

    def put(tool: str, c: Optional[str], answer: Any) -> None:
        out[file_name(backend, tool, case(c))] = answer

    put('dialect', None, side.tool('dialect'))
    put('stats', None, side.tool('stats', {'mode': 'full'}))
    put('stats', 'quick', side.tool('stats', {'mode': 'quick'}))
    put('documents', None, side.tool('documents', {'cursor': None, 'limit': 3, 'deleted': 'active', 'sort': 'path'}))
    put('chunks', None, side.tool('chunks', {'object_id': multi, 'after_chunk': -1, 'limit': 2, 'deleted': 'active'}))
    put('chunks', 'not_found', side.tool('chunks', {'object_id': 'schema'}))
    put('vectors', None, side.tool('vectors', {'keys': [[multi, 0]]}))
    sample = side.tool('sample', {'n': 40, 'seed': 7, 'mode': 'detailed', 'knn_k': 5})
    put('sample', None, sample)
    put('sample', 'light', side.tool('sample', {'n': 40, 'seed': 7, 'mode': 'light', 'knn_k': 5}))
    if isinstance(sample, dict) and sample.get('sample_id'):
        put(
            'project',
            None,
            side.tool(
                'project', {'sample_id': sample['sample_id'], 'vector': water, 'm': 3, 'with_similarities': True}
            ),
        )
    put('neighbors', None, side.tool('neighbors', {'key': [multi, 0], 'k': 3, 'exclude_self': True}))
    put('search', None, side.tool('search', {'vector': water, 'top_k': 3}))
    put(
        'search',
        'below_floor',
        side.tool(
            'search', {'vector': unrelated, 'top_k': 3, 'include_below_floor': True, 'include_below_threshold': True}
        ),
    )
    put('search', 'dimension_mismatch', side.tool('search', {'vector': water[:10], 'top_k': 3}))
    put('remove_document', 'reserved_id', side.tool('remove_document', {'object_ids': ['schema']}))
    put('remove_document', 'writes_source', side.tool('remove_document', {'object_ids': [multi]}, source='chat_1'))
    put('remove_document', 'writes_disabled', side.tool('remove_document', {'object_ids': [multi]}, node='store_2'))
    return out


def live_fixtures(only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Every live capture, by file name (starts its own engine; requires the services of the toolpath suite)."""
    import tempfile

    from . import test_vector_toolpath_full as tp

    corpus = tp.gen_corpus.build_corpus()
    names = [(rel, WIRE_PREFIX + rel) for rel in tp.CORPUS_DOCS]
    out: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix='vx-wire-') as tmp:
        root = Path(tmp)
        files = []
        for rel, name in names:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(corpus[rel], encoding='utf-8')
            files.append((path, name))
        broker = tp._Broker(tp._PgVector('rocketride_vector').broker_dsn())
        stub = tp._Stub(root)
        engine = tp._Engine(root / 'store', broker)
        try:
            for provider in tp.SUPPORTED:
                if only and provider not in only:
                    continue
                service = tp._service(provider)
                if service.unavailable():
                    raise RuntimeError(service.unavailable())
                backend = provider if provider != 'postgres' else 'pgvector'
                sides = []
                try:
                    new = tp._Side(
                        engine,
                        provider,
                        'new',
                        WIRE_COLLECTION,
                        tp._pipeline(provider, service, WIRE_COLLECTION, stub.url),
                        ('tools_1', 'chat_1', 'ingest_1'),
                    )
                    sides.append(new)
                    results = new.upload(files)
                    failed = [r.get('filepath') for r in results if r.get('action') != 'complete']
                    if failed:
                        raise RuntimeError(f'{provider}: uploads failed: {failed}')
                    multi = tp.object_id(WIRE_PREFIX + tp.MULTI_DOC)
                    (water,) = new.tool('embed', {'texts': [tp.WATER_QUESTION], 'kind': 'query'}, node='embed_1')[
                        'vectors'
                    ]
                    embed_answer = new.tool('embed', {'texts': [tp.WATER_QUESTION], 'kind': 'query'}, node='embed_1')
                    (unrelated,) = new.tool(
                        'embed', {'texts': [tp.UNRELATED_QUESTION], 'kind': 'query'}, node='embed_1'
                    )['vectors']
                    out[file_name(backend, 'embed')] = embed_answer
                    service.make_legacy(WIRE_COLLECTION, WIRE_LEGACY, multi)
                    legacy = tp._Side(
                        engine,
                        provider,
                        'legacy',
                        WIRE_LEGACY,
                        tp._pipeline(provider, service, WIRE_LEGACY, stub.url),
                        ('tools_1', 'chat_1', 'ingest_1'),
                    )
                    sides.append(legacy)
                    out.update(_captures_for(tp, new, 'new', backend, multi, water, unrelated))
                    second = tp.object_id(WIRE_PREFIX + 'field/kestrel_field_guide.md')
                    out.update(_captures_for(tp, legacy, 'legacy', backend, second, water, unrelated))
                    # Last, because it changes the data: a removal and what it reports.
                    out[file_name(backend, 'remove_document')] = new.tool('remove_document', {'object_ids': [second]})
                finally:
                    for side in sides:
                        side.stop()
                    for collection in (WIRE_COLLECTION, WIRE_LEGACY):
                        try:
                            service.drop(collection)
                        except Exception:  # noqa: BLE001 - best-effort clean-up
                            pass
        finally:
            engine.stop()
            stub.close()
            broker.close()
    return out


def committed(directory: Path) -> Dict[str, Any]:
    """The committed captures under directory, by relative file name."""
    return {
        p.relative_to(directory).as_posix(): json.loads(p.read_text(encoding='utf-8'))
        for p in sorted(directory.rglob('*.json'))
    }


def differences(regenerated: Dict[str, Any], on_disk: Dict[str, Any]) -> List[str]:
    """File names whose canonical form differs, is missing on disk or is not regenerated."""
    out = []
    for name in sorted(set(regenerated) | set(on_disk)):
        if name not in on_disk or name not in regenerated:
            out.append(name)
        elif stored(regenerated[name]) != on_disk[name]:
            out.append(name)
    return out


def _parse(argv: Iterable[str]) -> Tuple[Optional[str], Optional[List[str]]]:
    args = list(argv)
    only = None
    if '--only' in args:
        i = args.index('--only')
        only = [x.strip() for x in args[i + 1].split(',') if x.strip()]
        del args[i : i + 2]
    return (args[0] if len(args) == 1 else None), only


def main(argv) -> int:
    target, only = _parse(argv)
    if target is None:
        print(__doc__)
        return 2
    captures = live_fixtures(only)
    _write(Path(target), captures)
    print('\n'.join(sorted(captures)))
    return 0


if __name__ == '__main__':
    if not __package__:
        # Run as a script: import this module as part of the test package so
        # its relative import of the tool-path suite resolves.
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from test.vector_wire_fixtures import main as package_main

        sys.exit(package_main(sys.argv[1:]))
    sys.exit(main(sys.argv[1:]))
