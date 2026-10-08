# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Seed the legacy-shaped Vector Explorer collections (disposable local containers only).

A "legacy" collection is one written by the store drivers as they were before
the explorer: random point ids, no file size or ingest time, no ``meta``
column on pgvector, and some documents without their first chunk. The driver
suites and the tool-path suite run every explorer tool against these as well
as against new collections. Run this with an engine whose store drivers are
still the old ones, once; the collections are kept and later runs only verify
them (``--recreate`` drops and seeds them again).

Recipes, all named ``vx_legacy_docs``, ingesting the demo corpus
(``demo/gen_corpus.py``) under the upload name ``/srv/legacy/<folder>/<file>``
(the engine stores the path without its leading slash and derives the
objectId from the name as sent, which is how this script finds documents):

* pgvector (gx-pgvector): the table is created with the old driver's DDL plus
  the ``signature`` column the old insert writes (that driver cannot create
  the table itself: its DDL lacks the column), and the control row is inserted
  exactly as ``DocumentStoreBase.createCollection`` writes it. ``postgres.pipe``
  ingests the corpus; ``rocketride_vector.pipe`` (through the fake broker, the
  same database) ingests the ``kitchen`` folder again under
  ``/srv/legacy-rr/...``, so both old drivers have written rows.
* Qdrant (vx-qdrant) and Chroma (vx-chroma): ``qdrant.pipe`` and
  ``chroma.pipe`` ingest the corpus; the old drivers create the collection.

Then one document per backend loses its first chunk: the chunk-0 row or point
of ``manuals/long_manual.md`` is deleted through the database's own client.
The old drivers never lose chunk 0 by themselves on a fresh ingest: the
chunker hands every text chunk of a document to the embedding node in one
call, so the store sees a single write per document.

Verification (always run, also after seeding): exactly one control record; no
``meta`` column on pgvector; exactly one document (the long manual) without
chunk 0; every corpus document present. Exits 1 when any check fails.

Usage (from dist/server; the engine must run with RR_DB_BROKER_URL/TOKEN):
  ./engine <this folder>/seed_legacy.py [--only pgvector,qdrant,chroma] [--recreate] [--verify-only]
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import tempfile
import uuid

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import vx_fixtures as fx  # noqa: E402

LEGACY = 'vx_legacy_docs'
PREFIX = '/srv/legacy/'
RR_PREFIX = '/srv/legacy-rr/'
RR_FOLDER = 'kitchen'
ORPHAN_REL = 'manuals/long_manual.md'
BACKENDS = ('pgvector', 'qdrant', 'chroma')

# The old pgvector driver's DDL (store_postgres/postgres.py) plus the column its insert also writes.
LEGACY_DDL = (
    'CREATE TABLE {table} (id bigserial PRIMARY KEY, content text, objectId text, nodeId text, parent text, '
    'permissionId int, isDeleted boolean, chunkId int, isTable boolean, tableId int, vectorSize int, '
    'modelName text, embedding vector({dim}), signature text)'
)


def _guard(name: str) -> str:
    """Only the legacy names are ever dropped."""
    if not name.startswith('vx_legacy_'):
        raise ValueError(f'refusing to touch {name!r}: not a vx_legacy_ collection')
    return name


def _corpus():
    spec = importlib.util.spec_from_file_location('vx_gen_corpus', HERE / 'demo' / 'gen_corpus.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def corpus_names(corpus, prefix: str = PREFIX, folder: Optional[str] = None) -> List[str]:
    """Display paths of the corpus documents (optionally one folder)."""
    return [prefix + rel for rel in corpus.build_corpus() if folder is None or rel.split('/')[0] == folder]


def control_row(model: str = fx.EMBEDDING_MODEL, dim: int = fx.EMBEDDING_DIMENSION) -> Dict[str, Any]:
    """The control record exactly as createCollection writes it through the old pgvector driver."""
    return {
        'content': '',
        'objectid': 'schema',
        'nodeid': None,
        'parent': None,
        'permissionid': None,
        'isdeleted': True,
        'chunkid': 0,
        'istable': None,
        'tableid': None,
        'signature': None,
        'vectorsize': dim,
        'modelname': model,
        'embedding': '[' + ','.join(['0'] * dim) + ']',
    }


def orphans(rows: Sequence[Tuple[str, int]]) -> List[str]:
    """Return the objectIds (control record excluded) without chunk 0, from (objectId, chunkId) rows."""
    chunks: Dict[str, set] = {}
    for object_id, chunk_id in rows:
        if object_id == 'schema':
            continue
        chunks.setdefault(object_id, set()).add(int(chunk_id))
    return sorted(o for o, ids in chunks.items() if 0 not in ids)


def verdict(
    backend: str,
    *,
    control: int,
    orphan_ids: Sequence[str],
    expected_orphan: Optional[str],
    documents: int,
    expected_documents: int,
    missing: Sequence[str] = (),
    meta_column: Optional[bool] = None,
) -> List[str]:
    """Problems with one seeded collection (empty when it is as promised)."""
    problems = []
    if missing:
        problems.append(f'{backend}: {len(missing)} corpus documents missing, e.g. {list(missing)[:3]}')
    if control != 1:
        problems.append(f'{backend}: {control} control records (expected 1)')
    if meta_column:
        problems.append(f'{backend}: has a meta column (a legacy table has none)')
    if expected_orphan is None or list(orphan_ids) != [expected_orphan]:
        problems.append(
            f'{backend}: documents without chunk 0 = {list(orphan_ids)} (expected exactly [{expected_orphan}])'
        )
    if documents != expected_documents:
        problems.append(f'{backend}: {documents} documents (expected {expected_documents})')
    return problems


# ---------------------------------------------------------------------------
# pgvector
# ---------------------------------------------------------------------------


def _pg():
    import psycopg2

    conn = psycopg2.connect(
        dbname=fx.PG['database'],
        user=fx.PG['user'],
        password=fx.PG['password'],
        host=fx.PG['host'],
        port=fx.PG['port'],
        connect_timeout=5,
    )
    conn.autocommit = True
    return conn


def pg_exists(table: str) -> bool:
    with _pg() as conn, conn.cursor() as cur:
        cur.execute('SELECT to_regclass(%s) IS NOT NULL', (f'public.{table}',))
        return bool(cur.fetchone()[0])


def pg_create(table: str, recreate: bool) -> None:
    """Create the legacy table and its control row (dropping it first with --recreate)."""
    from psycopg2 import sql

    conn = _pg()
    try:
        with conn.cursor() as cur:
            if recreate:
                cur.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(_guard(table))))
            cur.execute(LEGACY_DDL.format(table=sql.Identifier(table).as_string(conn), dim=fx.EMBEDDING_DIMENSION))
            row = control_row()
            columns = list(row)
            cur.execute(
                sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table),
                    sql.SQL(', ').join(sql.Identifier(c) for c in columns),
                    sql.SQL(', ').join(
                        sql.SQL('%s::vector') if c == 'embedding' else sql.Placeholder() for c in columns
                    ),
                ),
                [row[c] for c in columns],
            )
    finally:
        conn.close()


def pg_chunk_ids(table: str, object_id: str) -> List[int]:
    from psycopg2 import sql

    with _pg() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL('SELECT chunkid FROM {} WHERE objectid = %s ORDER BY chunkid').format(sql.Identifier(table)),
            (object_id,),
        )
        return [r[0] for r in cur.fetchall()]


def pg_plant_orphan(table: str, object_id: str) -> int:
    from psycopg2 import sql

    with _pg() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL('DELETE FROM {} WHERE objectid = %s AND chunkid = 0').format(sql.Identifier(table)), (object_id,)
        )
        return cur.rowcount


def pg_facts(table: str) -> Dict[str, Any]:
    from psycopg2 import sql

    t = sql.Identifier(table)
    with _pg() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE objectid = 'schema'").format(t))
        control = cur.fetchone()[0]
        cur.execute(
            'SELECT count(*) FROM information_schema.columns WHERE table_name = %s AND column_name = %s',
            (table, 'meta'),
        )
        meta = cur.fetchone()[0] > 0
        cur.execute(
            sql.SQL(
                "SELECT objectid FROM {} WHERE objectid <> 'schema' GROUP BY objectid HAVING NOT bool_or(chunkid = 0) ORDER BY objectid"
            ).format(t)
        )
        orphan_ids = [r[0] for r in cur.fetchall()]
        cur.execute(sql.SQL("SELECT objectid, count(*) FROM {} WHERE objectid <> 'schema' GROUP BY objectid").format(t))
        counts = dict(cur.fetchall())
    return {
        'control': control,
        'meta_column': meta,
        'orphans': orphan_ids,
        'documents': len(counts),
        'chunks': sum(counts.values()),
        'object_ids': set(counts),
    }


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(host=fx.QDRANT['host'], port=fx.QDRANT['port'], timeout=30)


def _qdrant_points(collection: str) -> List[Dict[str, Any]]:
    client = _qdrant()
    out, offset = [], None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False
        )
        out.extend((p.payload or {}).get('meta') or {} for p in points)
        if offset is None:
            return out


def qdrant_exists(collection: str) -> bool:
    return _qdrant().collection_exists(collection)


def qdrant_drop(collection: str) -> None:
    client = _qdrant()
    if client.collection_exists(_guard(collection)):
        client.delete_collection(collection)


def qdrant_plant_orphan(collection: str, object_id: str) -> None:
    from qdrant_client import models

    _qdrant().delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key='meta.objectId', match=models.MatchValue(value=object_id)),
                    models.FieldCondition(key='meta.chunkId', match=models.MatchValue(value=0)),
                ]
            )
        ),
        wait=True,
    )


def qdrant_facts(collection: str) -> Dict[str, Any]:
    metas = _qdrant_points(collection)
    rows = [(m.get('objectId'), m.get('chunkId') or 0) for m in metas]
    docs = {o for o, _ in rows if o != 'schema'}
    return {
        'control': sum(1 for o, _ in rows if o == 'schema'),
        'orphans': orphans(rows),
        'documents': len(docs),
        'chunks': sum(1 for o, _ in rows if o != 'schema'),
        'object_ids': docs,
    }


# ---------------------------------------------------------------------------
# Chroma
# ---------------------------------------------------------------------------


def _chroma():
    import chromadb

    return chromadb.HttpClient(host=fx.CHROMA['host'], port=int(fx.CHROMA['port']))


def chroma_exists(collection: str) -> bool:
    return collection in {c if isinstance(c, str) else c.name for c in _chroma().list_collections()}


def chroma_drop(collection: str) -> None:
    if chroma_exists(_guard(collection)):
        _chroma().delete_collection(collection)


def _chroma_metas(collection: str) -> List[Dict[str, Any]]:
    return _chroma().get_collection(collection).get(include=['metadatas'])['metadatas'] or []


def chroma_plant_orphan(collection: str, object_id: str) -> None:
    _chroma().get_collection(collection).delete(where={'$and': [{'objectId': object_id}, {'chunkId': 0}]})


def chroma_facts(collection: str) -> Dict[str, Any]:
    rows = [(m.get('objectId'), m.get('chunkId') or 0) for m in _chroma_metas(collection)]
    docs = {o for o, _ in rows if o != 'schema'}
    return {
        'control': sum(1 for o, _ in rows if o == 'schema'),
        'orphans': orphans(rows),
        'documents': len(docs),
        'chunks': sum(1 for o, _ in rows if o != 'schema'),
        'object_ids': docs,
    }


# ---------------------------------------------------------------------------
# Ingest through the engine (the old drivers write the rows)
# ---------------------------------------------------------------------------


async def ingest(client, key: str, collection: str, files: Sequence[Tuple[Path, str]]) -> None:
    """Start the template's ingest source on ``collection``, upload, stop."""
    pipe = fx.build_pipeline(key, collection=collection, project_id=str(uuid.uuid4()), name=f'vx-legacy seed ({key})')
    tokens = await fx.ensure_started(client, pipe, ('ingest_1',))
    try:
        results = await fx.send_named(client, tokens['ingest_1'], files)
        failed = fx.failed_uploads(results)
        if failed:
            raise RuntimeError(f'{key}: {len(failed)} uploads did not complete: {failed[:3]}')
    finally:
        await client.terminate(tokens['ingest_1'])


async def seed(backends: Sequence[str], recreate: bool) -> Dict[str, Any]:
    """Seed the selected backends that are missing (or all of them with --recreate)."""
    from rocketride import RocketRideClient

    corpus = _corpus()
    notes: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix='vx-legacy-') as tmp:
        root = Path(tmp)
        written = corpus.write_corpus(root)
        files = [(p, PREFIX + p.relative_to(root).as_posix()) for p in written]
        rr_files = [
            (p, RR_PREFIX + p.relative_to(root).as_posix())
            for p in written
            if p.relative_to(root).parts[0] == RR_FOLDER
        ]
        orphan_id = fx.object_id(PREFIX + ORPHAN_REL)
        async with RocketRideClient(uri=fx.ENGINE_URL, auth=fx.API_KEY, request_timeout=900000) as client:
            if 'pgvector' in backends and (recreate or not pg_exists(LEGACY)):
                pg_create(LEGACY, recreate)
                await ingest(client, 'postgres', LEGACY, files)
                await ingest(client, 'rocketride_vector', LEGACY, rr_files)
                kept = pg_chunk_ids(LEGACY, orphan_id)
                notes['pgvector'] = {
                    'long_manual_chunks': len(kept),
                    'long_manual_kept_chunk0': bool(kept) and kept[0] == 0,
                    'planted_rows': pg_plant_orphan(LEGACY, orphan_id),
                }
            if 'qdrant' in backends and (recreate or not qdrant_exists(LEGACY)):
                if recreate:
                    qdrant_drop(LEGACY)
                await ingest(client, 'qdrant', LEGACY, files)
                qdrant_plant_orphan(LEGACY, orphan_id)
                notes['qdrant'] = 'seeded'
            if 'chroma' in backends and (recreate or not chroma_exists(LEGACY)):
                if recreate:
                    chroma_drop(LEGACY)
                await ingest(client, 'chroma', LEGACY, files)
                chroma_plant_orphan(LEGACY, orphan_id)
                notes['chroma'] = 'seeded'
    return notes


def verify(backends: Sequence[str]) -> Tuple[Dict[str, Any], List[str]]:
    """Facts and problems for every selected backend."""
    corpus = _corpus()
    expected_ids = {fx.object_id(n) for n in corpus_names(corpus)}
    rr_ids = {fx.object_id(n) for n in corpus_names(corpus, RR_PREFIX, RR_FOLDER)}
    orphan_id = fx.object_id(PREFIX + ORPHAN_REL)
    facts: Dict[str, Any] = {}
    problems: List[str] = []
    for backend, exists, facts_of, wanted in (
        ('pgvector', pg_exists, pg_facts, expected_ids | rr_ids),
        ('qdrant', qdrant_exists, qdrant_facts, expected_ids),
        ('chroma', chroma_exists, chroma_facts, expected_ids),
    ):
        if backend not in backends:
            continue
        if not exists(LEGACY):
            problems.append(f'{backend}: {LEGACY} does not exist')
            continue
        f = facts_of(LEGACY)
        present = f.pop('object_ids')
        f['orphan_expected'] = orphan_id
        facts[backend] = f
        problems += verdict(
            backend,
            control=f['control'],
            orphan_ids=f['orphans'],
            expected_orphan=orphan_id,
            documents=f['documents'],
            expected_documents=len(wanted),
            missing=sorted(wanted - present),
            meta_column=f.get('meta_column'),
        )
    return facts, problems


def main() -> int:
    """Seed what is missing, then verify every selected backend."""
    parser = argparse.ArgumentParser(
        description='Seed and verify the legacy Vector Explorer collections (local containers only).'
    )
    parser.add_argument('--only', default=','.join(BACKENDS))
    parser.add_argument('--recreate', action='store_true', help=f'drop {LEGACY} first and seed again')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    backends = [b.strip() for b in args.only.split(',') if b.strip()]
    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        parser.error(f'unknown backend(s): {", ".join(unknown)}')
    notes = {} if args.verify_only else asyncio.run(seed(backends, args.recreate))
    facts, problems = verify(backends)
    print(json.dumps({'seeded': notes, 'facts': facts, 'problems': problems}, indent=2, default=str))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
