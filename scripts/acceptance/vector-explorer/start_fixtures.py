# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Start the Vector Explorer fixture pipelines (local disposable containers only).

Each fixture is one of the shipped templates (``apps/vector-ui/templates``)
pointed at a local container: ``postgres.pipe`` at gx-pgvector,
``rocketride_vector.pipe`` through the fake DB broker, ``qdrant.pipe`` at
vx-qdrant and ``chroma.pipe`` at vx-chroma. The script fills in a fixed
local-only project id and display name, sets the store connection on
``store_1`` and ``store_2``, and starts the three sources (``tools_1``,
``chat_1``, ``ingest_1``) with ``ttl=0`` so the engine does not stop them after
its idle timeout. Only what is not running yet is started; ``--stop``
terminates the fixtures' tasks. It never creates, drops or rewrites a table or
collection: the stores create their collection on the first ingest.

``--llm stub`` (the default) points ``llm_1`` at the local test stub
(``stub_llm.py``, http://127.0.0.1:18901/v1) and names it "Local stub LLM";
``--llm template`` leaves the template's placeholder key in place, to record
how the chat source behaves without a real key.

Before starting, it warms the tiktoken encodings the LLM node counts tokens
with, so the first chat does not wait for a download (best effort: offline it
says so and goes on).

Prints names and project ids only, never tokens. Every default below is a
throwaway LOCAL-ONLY test value for a disposable container, not a secret.

Usage (from dist/server): ./engine <this folder>/start_fixtures.py [--only postgres,qdrant] [--llm stub|template] [--stop]
The engine must run with RR_DB_BROKER_URL/RR_DB_BROKER_TOKEN for the rocketride_vector fixture (see README.md).
"""

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path

from rocketride import RocketRideClient

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# Engine under test. An OSS engine started without ROCKETRIDE_APIKEY accepts any
# non-empty key, so RR_TEST_APIKEY is a local label, not a credential.
ENGINE_URL = os.environ.get('ENGINE_URL', 'http://127.0.0.1:5590')
API_KEY = os.environ.get('RR_TEST_APIKEY', 'local-acceptance-key')
TEMPLATES = Path(os.environ.get('VX_TEMPLATES_DIR', str(REPO / 'apps' / 'vector-ui' / 'templates')))
STUB_LLM_URL = os.environ.get('VX_STUB_LLM_URL', 'http://127.0.0.1:18901/v1')
COLLECTION = os.environ.get('VX_COLLECTION', 'vx_demo_docs')

PG = {
    'host': os.environ.get('VX_PG_HOST', '127.0.0.1'),
    'port': int(os.environ.get('VX_PG_PORT', '55432')),
    'user': os.environ.get('VX_PG_USER', 'rruser'),
    'password': os.environ.get('VX_PG_PASSWORD', 'rrpass'),
    'database': os.environ.get('VX_PG_DATABASE', 'rrtenant'),
}
QDRANT = {'host': os.environ.get('VX_QDRANT_HOST', '127.0.0.1'), 'port': int(os.environ.get('VX_QDRANT_PORT', '56333'))}
CHROMA = {'host': os.environ.get('VX_CHROMA_HOST', '127.0.0.1'), 'port': os.environ.get('VX_CHROMA_PORT', '58000')}

# The three sources, in start order (the Tools source is the cheapest to start).
SOURCES = ('tools_1', 'chat_1', 'ingest_1')

# key -> (display name, fixed local-only project id, template stem, connection settings for the store profile).
# The browser lanes find the fixtures by these display names (env.cjs FIXTURES).
FIXTURES = {
    'postgres': (
        'vx-local Vector (pgvector)',
        '00000000-0000-4000-8000-00000000d1a1',
        'postgres',
        {**PG, 'collection': COLLECTION},
    ),
    'rocketride_vector': (
        'vx-local Vector (RocketRide Vector)',
        '00000000-0000-4000-8000-00000000d1a2',
        'rocketride_vector',
        {'collection': os.environ.get('VX_RR_TABLE', 'vx_demo_rr')},
    ),
    'qdrant': (
        'vx-local Vector (Qdrant)',
        '00000000-0000-4000-8000-00000000d1a3',
        'qdrant',
        {**QDRANT, 'collection': COLLECTION},
    ),
    'chroma': (
        'vx-local Vector (Chroma)',
        '00000000-0000-4000-8000-00000000d1a4',
        'chroma',
        {**CHROMA, 'collection': COLLECTION},
    ),
}


def build_pipeline(key: str, llm: str) -> dict:
    """Load one template and fill in the fixture's identity, store connection and LLM."""
    name, project_id, stem, connection = FIXTURES[key]
    pipe = json.loads((TEMPLATES / f'{stem}.pipe').read_text(encoding='utf-8'))
    pipe = copy.deepcopy(pipe)
    pipe['name'] = name
    pipe['project_id'] = project_id
    for comp in pipe['components']:
        if comp['id'] in ('store_1', 'store_2'):
            profile = comp['config']['profile']
            comp['config'][profile].update(connection)
        elif comp['id'] == 'llm_1' and llm == 'stub':
            comp['name'] = 'Local stub LLM'
            comp['config']['custom'].update({'base_url': STUB_LLM_URL, 'apikey': 'local-stub-not-a-key'})
    return pipe


def warm_tiktoken() -> None:
    """Load the tiktoken encodings once so the LLM node finds them in the local cache."""
    try:
        import tiktoken
    except ImportError:
        print('tiktoken is not installed in this Python; the first chat may wait for its download')
        return
    for encoding in ('o200k_base', 'cl100k_base'):
        try:
            tiktoken.get_encoding(encoding)
            print(f'tiktoken {encoding}: cached')
        except Exception as e:  # noqa: BLE001 - offline is reported, not fatal
            print(f'tiktoken {encoding}: not cached ({type(e).__name__}); the first chat may wait for it')


async def main() -> None:
    """Start (or with --stop, terminate) the selected fixtures."""
    parser = argparse.ArgumentParser(description='Start the Vector Explorer fixture pipelines (local containers only).')
    parser.add_argument('--only', default='', help='comma-separated fixture keys: ' + ', '.join(FIXTURES))
    parser.add_argument('--llm', choices=('stub', 'template'), default='stub')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-warm-tiktoken', action='store_true')
    args = parser.parse_args()

    keys = [k.strip() for k in args.only.split(',') if k.strip()] or list(FIXTURES)
    unknown = [k for k in keys if k not in FIXTURES]
    if unknown:
        parser.error(f'unknown fixture(s): {", ".join(unknown)}')
    if not args.stop and not args.no_warm_tiktoken:
        warm_tiktoken()

    # A first start installs and loads the embedding model, which can take minutes.
    async with RocketRideClient(uri=ENGINE_URL, auth=API_KEY, request_timeout=900000) as client:
        running = {}
        for task in await client.get_tasks():
            pid = (task.get('pipeline') or {}).get('project_id')
            running[(pid, task.get('source'))] = task
        for key in keys:
            name, project_id, _stem, _connection = FIXTURES[key]
            if args.stop:
                for source in SOURCES:
                    task = running.get((project_id, source))
                    if task is not None:
                        await client.terminate(task['token'])
                        print(f'stopped {name} / {source}')
                continue
            pipe = build_pipeline(key, args.llm)
            for source in SOURCES:
                if (project_id, source) in running:
                    print(f'running {name} / {source} ({project_id})')
                    continue
                try:
                    # ttl=0: run until --stop (the engine stops a task idle for its TTL, 15 minutes by default).
                    await client.use(pipeline=pipe, source=source, ttl=0)
                    print(f'started {name} / {source} ({project_id})')
                except Exception as e:  # noqa: BLE001 - the other fixtures still start
                    print(f'FAILED {name} / {source}: {type(e).__name__}: {str(e)[:200]}')


if __name__ == '__main__':
    asyncio.run(main())
