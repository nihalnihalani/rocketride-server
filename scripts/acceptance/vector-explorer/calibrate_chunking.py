# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Measure the chunk sizes the templates' chunker produces on the demo corpus (G0-6).

For each candidate ``chunk_1`` configuration it starts a small pipeline on the
engine under test, ``dropper -> parse -> chunk_1 -> response_documents``,
sends every file of the demo corpus (``demo/gen_corpus.py``) through it and
reads the chunks back from the upload results. No embedding model and no store
are involved, so a run takes seconds.

The aim (median chunk 400-1,200 characters) comes from the design: the stock
chunker settings make chunks so large that a one-page document is a single
point on the map and generic questions score below the store's floor.

Prints one JSON report. With ``--write`` it records the chosen candidate in
``apps/vector-ui/tests/fixtures/chunking.json`` (``calibrated: true`` plus the
measurement) and puts its ``chunk_1`` configuration into all nine templates.

Usage (from dist/server):
  ./engine <this folder>/calibrate_chunking.py [--strlen 512,800,1000] [--write N]
Settings: ENGINE_URL, RR_TEST_APIKEY (see README.md).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import uuid

from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TEMPLATES = REPO / 'apps' / 'vector-ui' / 'templates'
CHUNKING = REPO / 'apps' / 'vector-ui' / 'tests' / 'fixtures' / 'chunking.json'

ENGINE_URL = os.environ.get('ENGINE_URL', 'http://127.0.0.1:5590')
API_KEY = os.environ.get('RR_TEST_APIKEY', 'local-acceptance-key')

TARGET = (400, 1200)
DEFAULT_CANDIDATES = (512, 800, 1000, 1200)


def chunk_config(strlen: int) -> Dict[str, Any]:
    """The chunk_1 configuration of one candidate (the node's default profile, one length)."""
    return {
        'profile': 'default',
        'default': {'mode': 'strlen', 'splitter': 'RecursiveCharacterTextSplitter', 'strlen': strlen},
        'parameters': {},
    }


def probe_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build dropper -> parse -> chunk_1 -> response_documents, with the template's parse and chunk lanes."""

    def source(cid: str, provider: str, name: str) -> Dict[str, Any]:
        return {
            'id': cid,
            'provider': provider,
            'name': name,
            'config': {'hideForm': True, 'mode': 'Source', 'parameters': {}, 'type': provider, 'name': name},
        }

    return {
        'name': 'vx-calibrate chunking',
        'project_id': str(uuid.uuid4()),
        'components': [
            source('ingest_1', 'dropper', 'Ingest'),
            {
                'id': 'parse_1',
                'provider': 'parse',
                'name': 'Parse',
                'config': {'index': {'maxFileSize': 52428800}},
                'input': [{'lane': 'tags', 'from': 'ingest_1'}],
            },
            {
                'id': 'chunk_1',
                'provider': 'preprocessor_langchain',
                'name': 'Chunker',
                'config': config,
                'input': [{'lane': 'text', 'from': 'parse_1'}, {'lane': 'table', 'from': 'parse_1'}],
            },
            {
                'id': 'response_1',
                'provider': 'response_documents',
                'name': 'Return Documents',
                'config': {'laneName': 'documents'},
                'input': [{'lane': 'documents', 'from': 'chunk_1'}],
            },
        ],
    }


def summarise(lengths_by_doc: Dict[str, List[int]], long_doc: str) -> Dict[str, Any]:
    """Median, spread and counts of one candidate's chunks."""
    lengths = [n for doc in lengths_by_doc.values() for n in doc]
    if not lengths:
        return {'chunks': 0, 'documents': len(lengths_by_doc)}
    deciles = statistics.quantiles(lengths, n=10) if len(lengths) > 1 else [lengths[0]] * 9
    return {
        'documents': len(lengths_by_doc),
        'chunks': len(lengths),
        'median_chars': int(statistics.median(lengths)),
        'p10_chars': int(deciles[0]),
        'p90_chars': int(deciles[-1]),
        'max_chars': max(lengths),
        'single_chunk_documents': sum(1 for doc in lengths_by_doc.values() if len(doc) == 1),
        'long_document_chunks': len(lengths_by_doc.get(long_doc, [])),
    }


def in_target(summary: Dict[str, Any]) -> bool:
    """True when the candidate's median chunk is inside the design's 400-1,200 characters."""
    return TARGET[0] <= summary.get('median_chars', 0) <= TARGET[1]


def setting_ignored(candidates: Dict[str, Dict[str, Any]]) -> bool:
    """True when two or more different lengths produced the very same chunks: the chunker ignores strlen."""
    summaries = [{k: v for k, v in s.items() if k != 'in_target'} for s in candidates.values()]
    return len(summaries) > 1 and all(s == summaries[0] for s in summaries[1:])


async def measure(client, files: List[Path], root: Path, strlen: int) -> Dict[str, List[int]]:
    """Run one candidate over the corpus; chunk lengths by relative path."""
    task = await client.use(pipeline=probe_pipeline(chunk_config(strlen)), source='ingest_1', ttl=0)
    try:
        out: Dict[str, List[int]] = {}
        for path in files:
            rel = path.relative_to(root).as_posix()
            (result,) = await client.send_files([(str(path), {'name': f'calibrate/{rel}'})], task['token'])
            documents = ((result or {}).get('result') or {}).get('documents') or []
            out[rel] = [len(d.get('page_content') or '') for d in documents]
        return out
    finally:
        await client.terminate(task['token'])


def write_choice(strlen: int, summary: Dict[str, Any], candidates: Dict[str, Any], corpus_note: str) -> None:
    """Record the chosen candidate in chunking.json and every template's chunk_1.

    A ``known_issue`` already recorded in chunking.json is kept.
    """
    config = chunk_config(strlen)
    previous = json.loads(CHUNKING.read_text(encoding='utf-8')) if CHUNKING.exists() else {}
    record = {
        'calibrated': True,
        'note': (
            'Measured by scripts/acceptance/vector-explorer/calibrate_chunking.py on the demo corpus '
            f'({corpus_note}); the design asks for a median chunk of {TARGET[0]}-{TARGET[1]:,} characters. '
            'Every template carries this chunk_1 configuration.'
        ),
        'target_median_chars': list(TARGET),
        'measured': summary,
        'candidates': candidates,
        'chunk_1': {'provider': 'preprocessor_langchain', 'config': config},
    }
    if 'known_issue' in previous:
        record['known_issue'] = previous['known_issue']
    CHUNKING.write_text(json.dumps(record, indent='\t') + '\n', encoding='utf-8')
    for template in sorted(TEMPLATES.glob('*.pipe')):
        pipe = json.loads(template.read_text(encoding='utf-8'))
        (chunker,) = [c for c in pipe['components'] if c['id'] == 'chunk_1']
        chunker['provider'] = 'preprocessor_langchain'
        chunker['config'] = config
        template.write_text(json.dumps(pipe, indent=2) + '\n', encoding='utf-8')


def _load_corpus_module():
    spec = importlib.util.spec_from_file_location('vx_gen_corpus', HERE / 'demo' / 'gen_corpus.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main() -> int:
    """Measure the candidates; optionally write the chosen one."""
    from rocketride import RocketRideClient

    parser = argparse.ArgumentParser(description='Measure chunk sizes for the Vector Explorer templates (G0-6).')
    parser.add_argument('--strlen', default=','.join(map(str, DEFAULT_CANDIDATES)))
    parser.add_argument('--write', type=int, default=None, help='record this candidate (must be in target)')
    args = parser.parse_args()
    candidates = [int(x) for x in args.strlen.split(',') if x.strip()]

    corpus = _load_corpus_module()
    with tempfile.TemporaryDirectory(prefix='vx-calibrate-') as tmp:
        root = Path(tmp)
        files = corpus.write_corpus(root)
        report: Dict[str, Any] = {'corpus_documents': len(files), 'candidates': {}}
        async with RocketRideClient(uri=ENGINE_URL, auth=API_KEY, request_timeout=600000) as client:
            for strlen in candidates:
                lengths = await measure(client, files, root, strlen)
                summary = summarise(lengths, corpus.LONG_MANUAL)
                summary['in_target'] = in_target(summary)
                report['candidates'][str(strlen)] = summary
    report['strlen_ignored'] = setting_ignored(report['candidates'])
    print(json.dumps(report, indent=2))
    if report['strlen_ignored']:
        print(
            "every length produced the same chunks: this engine's preprocessor_langchain does not pass "
            "strlen to its splitter (chunks stop at the splitter's own 4,000-character default)",
            file=sys.stderr,
        )
    if args.write is not None:
        chosen = report['candidates'].get(str(args.write))
        if report['strlen_ignored'] or not chosen or not chosen['in_target']:
            print(
                f'refusing to write strlen {args.write}: ignored, not measured or outside the target', file=sys.stderr
            )
            return 1
        write_choice(args.write, chosen, report['candidates'], f'{len(files)} documents, demo/gen_corpus.py')
        print(
            f'wrote strlen {args.write} to {CHUNKING.relative_to(REPO)} and {len(list(TEMPLATES.glob("*.pipe")))} templates'
        )
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
