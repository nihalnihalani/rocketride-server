# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Start long-lived tools pipelines for the browser lanes (local disposable databases only).

Starts SQL pipelines (db_postgres, db_supabase, rocketride_sql) and one tools-only
graph pipeline per engine, each with a fixed local-only project id so reruns
reuse them, then exits and leaves the tasks running. Before starting, it makes
sure the SQL fixture table (SQL_TABLE, default gx_items) exists with 25 rows;
it never drops or rewrites an existing table. Prints names and project ids only,
never tokens. ``--stop`` terminates the fixtures.

Run graph_acceptance.py first: it seeds the ACCEPT_GRAPH graphs these fixtures
read. Run browser/gen_perf.py first too: the perf fixture does not start until
PERF_GRAPH exists (rerunning this script then starts only what is missing).

Usage (from dist/server): ./engine <this folder>/start_fixtures.py [--stop]
Settings come from the environment; see local_env.py.
"""

import asyncio
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_env as E  # noqa: E402 - after the sys.path line above
from rocketride import RocketRideClient  # noqa: E402

SQL = {
    'host': E.SQL_HOST,
    'user': E.SQL_USER,
    'password': E.SQL_PASSWORD,
    'database': E.SQL_DATABASE,
    'table': E.SQL_TABLE,
}
NEO4J = {'uri': E.NEO4J_URI, 'user': E.NEO4J_USER, 'password': E.NEO4J_PASSWORD}
FALKOR = {'host': E.FALKORDB_HOST, 'port': E.FALKORDB_PORT}

# (display name, fixed local-only project id, provider, node config). The browser
# lanes find the fixtures by these display names (env.cjs FIXTURES).
FIXTURES = [
    ('gx-local SQL (pgvector)', '00000000-0000-4000-8000-00000000c501', 'db_postgres', {**SQL, 'allow_execute': False}),
    (
        'gx-local Graph (AGE)',
        '00000000-0000-4000-8000-00000000a6e1',
        'rocketride_graph',
        {'graph': E.ACCEPT_GRAPH, 'allow_execute': False},
    ),
    (
        'gx-local Graph (Neo4j)',
        '00000000-0000-4000-8000-00000000e041',
        'graph_neo4j',
        {**NEO4J, 'allow_execute': False},
    ),
    (
        'gx-local SQL write-enabled (pgvector)',
        '00000000-0000-4000-8000-00000000c502',
        'db_postgres',
        {**SQL, 'allow_execute': True},
    ),
    (
        'gx-local Supabase preset (pgvector)',
        '00000000-0000-4000-8000-00000000c503',
        'db_supabase',
        {**SQL, 'allow_execute': False},
    ),
    (
        'gx-local RocketRide SQL (fake broker)',
        '00000000-0000-4000-8000-00000000c504',
        'rocketride_sql',
        {'allow_execute': False, 'table': E.SQL_TABLE},
    ),
    (
        'gx-local Graph perf (FalkorDB)',
        '00000000-0000-4000-8000-00000000fa1d',
        'graph_falkordb',
        {**FALKOR, 'graph': E.PERF_GRAPH, 'allow_execute': False},
    ),
    (
        'gx-local Graph (FalkorDB)',
        '00000000-0000-4000-8000-00000000fa1c',
        'graph_falkordb',
        {**FALKOR, 'graph': E.ACCEPT_GRAPH, 'allow_execute': False},
    ),
]


def ensure_sql_table() -> None:
    """Create the SQL fixture table with rows 'item 1'..'item 25' when it does not exist yet."""
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(E.sql_dsn())
    try:
        with conn, conn.cursor() as cur:
            cur.execute('SELECT to_regclass(%s)', (E.SQL_TABLE,))
            if cur.fetchone()[0] is not None:
                print(f'sql table {E.SQL_TABLE} exists (left unchanged)')
                return
            table = sql.Identifier(E.SQL_TABLE)
            cur.execute(sql.SQL('CREATE TABLE {} (id serial PRIMARY KEY, name text, qty integer)').format(table))
            cur.execute(
                sql.SQL("INSERT INTO {} (name, qty) SELECT 'item ' || g, g FROM generate_series(1, 25) g").format(table)
            )
            print(f'sql table {E.SQL_TABLE} created with 25 rows')
    finally:
        conn.close()


def pipeline(name, project_id, provider, cfg):
    return {
        'name': name,
        'project_id': project_id,
        'components': [
            E.TOOLS_SOURCE,
            {
                'id': f'{provider}_1',
                'provider': provider,
                'name': name.split('(')[-1].rstrip(')'),
                'config': {'profile': 'default', 'default': cfg, 'name': provider},
                'control': [{'classType': 'tool', 'from': 'tools_1'}],
            },
        ],
    }


async def main():
    stop = '--stop' in sys.argv
    if not stop:
        ensure_sql_table()
    async with RocketRideClient(uri=E.ENGINE_URL, auth=E.API_KEY) as client:
        running = {(t.get('pipeline') or {}).get('project_id'): t for t in await client.get_tasks()}
        for name, pid, provider, cfg in FIXTURES:
            if stop:
                if pid in running:
                    await client.terminate(running[pid]['token'])
                    print(f'stopped {name}')
                continue
            if pid in running:
                print(f'running {name} ({pid})')
                continue
            try:
                await client.use(pipeline=pipeline(name, pid, provider, cfg), source='tools_1')
                print(f'started {name} ({pid})')
            except Exception as e:  # noqa: BLE001
                print(f'FAILED {name}: {type(e).__name__}: {str(e)[:200]}')


asyncio.run(main())
