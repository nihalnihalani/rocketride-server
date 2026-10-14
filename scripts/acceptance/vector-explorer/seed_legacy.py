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

Verification (always run, also after seeding): exactly one control record;
exactly one document (the long manual) without chunk 0; every corpus document
present; the long manual still has at least 64 rows and the median chunk is
400-1,200 characters, the calibrated chunking of
``apps/vector-ui/tests/fixtures/chunking.json`` (a seed on an engine whose
chunker ignores ``strlen``, about 36 chunks of up to 4,000 characters for the
manual, fails here); and the old drivers' shape. On Qdrant and Chroma every
point id is a random (version 4) uuid, never the ``objectId#chunkId`` uuid5 the
explorer's drivers derive, the metadata holds only the old keys
(``LEGACY_META_KEYS``, plus ``vectorSize``/``modelName`` on the control record)
and a Qdrant payload only ``content`` and ``meta``. On pgvector the table has
exactly the old columns (``LEGACY_COLUMNS``); a ``meta`` column is allowed only
when this run did not seed the table (a newer driver adds it when it first opens
the table), and no row may carry ``meta``. Exits 1 when any check fails.

Before anything is created or dropped, the seed asks the chunker node the
engine imports (``engine_chunker``) what it would cut from
the corpus with the templates' ``chunk_1`` length, and refuses to seed when
that is not the calibrated shape (``ChunkerRefused``, exit 1): the chunker node
as it stands drops the length (see the README), so a seed on it would replace
good collections with ones that fail the verification above.

Usage (from dist/server; the engine must run with RR_DB_BROKER_URL/TOKEN):
  ./engine <this folder>/seed_legacy.py [--only pgvector,qdrant,chroma] [--recreate] [--verify-only]
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import importlib.util
import json
import statistics
import sys
import tempfile
import uuid

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import calibrate_chunking as cal  # noqa: E402
import vx_fixtures as fx  # noqa: E402

LEGACY = 'vx_legacy_docs'
PREFIX = '/srv/legacy/'
RR_PREFIX = '/srv/legacy-rr/'
RR_FOLDER = 'kitchen'
ORPHAN_REL = 'manuals/long_manual.md'
BACKENDS = ('pgvector', 'qdrant', 'chroma')
# The chunker node in the repository; an engine runs its own copy (dist/server/nodes).
REPO_CHUNKER = cal.NODE
# The long manual has more than 64 chunks at the calibrated chunking, so at least 64 rows once chunk 0 is gone.
LONG_MANUAL_MIN_ROWS = 64
# The calibrated median chunk (apps/vector-ui/tests/fixtures/chunking.json target_median_chars).
MEDIAN_CHARS = (400, 1200)

# The old pgvector driver's DDL (store_postgres/postgres.py) plus the column its insert also writes.
LEGACY_DDL = (
    'CREATE TABLE {table} (id bigserial PRIMARY KEY, content text, objectId text, nodeId text, parent text, '
    'permissionId int, isDeleted boolean, chunkId int, isTable boolean, tableId int, vectorSize int, '
    'modelName text, embedding vector({dim}), signature text)'
)

# What the old drivers write, and nothing more. pgvector: exactly the columns of LEGACY_DDL (a newer
# driver adds a ``meta`` column when it opens the table and fills it on every row it writes) ...
LEGACY_COLUMNS = frozenset(
    (
        'id',
        'content',
        'objectid',
        'nodeid',
        'parent',
        'permissionid',
        'isdeleted',
        'chunkid',
        'istable',
        'tableid',
        'vectorsize',
        'modelname',
        'embedding',
        'signature',
    )
)
# ... Qdrant and Chroma: the metadata of DocMetadata's own fields (the explorer's drivers add
# ingestedAt, size and modifyTime), with the control record's two keys besides ...
LEGACY_META_KEYS = frozenset(
    ('objectId', 'chunkId', 'nodeId', 'parent', 'permissionId', 'isDeleted', 'isTable', 'tableId', 'signature')
)
CONTROL_META_KEYS = frozenset(('vectorSize', 'modelName'))
# ... a Qdrant payload of these keys, and random (uuid4) point ids, never the derived ``derived_id``.
QDRANT_PAYLOAD_KEYS = frozenset(('content', 'meta'))


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


def median_length(contents: Sequence[str]) -> Optional[int]:
    """Median length of the non-empty contents (the control record's content is empty); None when there are none."""
    lengths = sorted(len(c) for c in contents if c)
    return int(statistics.median(lengths)) if lengths else None


def orphans(rows: Sequence[Tuple[str, int]]) -> List[str]:
    """Return the objectIds (control record excluded) without chunk 0, from (objectId, chunkId) rows."""
    chunks: Dict[str, set] = {}
    for object_id, chunk_id in rows:
        if object_id == 'schema':
            continue
        chunks.setdefault(object_id, set()).add(int(chunk_id))
    return sorted(o for o, ids in chunks.items() if 0 not in ids)


def derived_id(object_id: Any, chunk_id: Any) -> str:
    """The point id the explorer's Qdrant and Chroma drivers derive for a chunk; the old drivers' ids are random."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'{object_id}#{int(chunk_id)}'))


def _id_version(point_id: Any) -> str:
    """'4' for a random uuid; another uuid version, 'integer' or 'not a uuid' otherwise."""
    if isinstance(point_id, int):
        return 'integer'
    try:
        return str(uuid.UUID(str(point_id)).version)
    except ValueError:
        return 'not a uuid'


def point_shape(records: Iterable[Tuple[Any, Dict[str, Any], Iterable[str]]]) -> Dict[str, Any]:
    """The shape of (point id, metadata, payload keys) records: id versions, derived ids, every key seen.

    ``chunks`` counts the records other than the control record.
    """
    versions: Dict[str, int] = collections.Counter()
    derived, points, chunks = 0, 0, 0
    meta_keys: set = set()
    payload_keys: set = set()
    for point_id, meta, keys in records:
        points += 1
        chunks += meta.get('objectId') != 'schema'
        versions[_id_version(point_id)] += 1
        try:
            derived += str(point_id) == derived_id(meta.get('objectId'), meta.get('chunkId') or 0)
        except (TypeError, ValueError):
            pass
        meta_keys.update(meta)
        payload_keys.update(keys)
    return {
        'points': points,
        'chunks': chunks,
        'id_versions': dict(versions),
        'derived_ids': derived,
        'meta_keys': sorted(meta_keys),
        'payload_keys': sorted(payload_keys),
    }


def shape_problems(backend: str, shape: Optional[Dict[str, Any]], seeded_now: bool = False) -> List[str]:
    """Where a collection is not in the old drivers' shape (empty when it is; see the module docstring)."""
    if not shape:
        return [f'{backend}: its shape was not read']
    problems = []
    if backend == 'pgvector':
        columns = set(shape.get('columns') or ())
        missing = sorted(LEGACY_COLUMNS - columns)
        extra = sorted(columns - LEGACY_COLUMNS - (set() if seeded_now else {'meta'}))
        if missing:
            problems.append(f'pgvector: columns of the old DDL missing: {missing}')
        if extra:
            problems.append(
                f'pgvector: columns the old driver never had: {extra}'
                + (' (a meta column right after seeding: a newer driver opened the table)' if 'meta' in extra else '')
            )
        if not shape.get('rows'):
            problems.append('pgvector: no rows besides the control record to read the shape of')
        if shape.get('meta_rows'):
            problems.append(f'pgvector: {shape["meta_rows"]} rows carry meta (written by a newer driver)')
        return problems
    if not shape.get('chunks'):
        problems.append(f'{backend}: no points besides the control record to read the shape of')
    other = {v: n for v, n in (shape.get('id_versions') or {}).items() if v != '4'}
    if other:
        problems.append(f'{backend}: {sum(other.values())} point ids are not random (version 4) uuids: {other}')
    if shape.get('derived_ids'):
        problems.append(
            f"{backend}: {shape['derived_ids']} point ids are derived from objectId#chunkId (the new drivers' ids)"
        )
    keys = sorted(set(shape.get('meta_keys') or ()) - LEGACY_META_KEYS - CONTROL_META_KEYS)
    if keys:
        problems.append(f'{backend}: metadata keys the old drivers never wrote: {keys}')
    if backend == 'qdrant':
        keys = sorted(set(shape.get('payload_keys') or ()) - QDRANT_PAYLOAD_KEYS)
        if keys:
            problems.append(f'qdrant: payload keys the old driver never wrote: {keys}')
    return problems


def verdict(
    backend: str,
    *,
    control: int,
    orphan_ids: Sequence[str],
    expected_orphan: Optional[str],
    documents: int,
    expected_documents: int,
    missing: Sequence[str] = (),
    long_manual_chunks: Optional[int] = None,
    median_chunk_chars: Optional[int] = None,
    shape: Optional[Dict[str, Any]] = None,
    seeded_now: bool = False,
) -> List[str]:
    """Problems with one seeded collection (empty when it is as promised; a shape not read is a problem)."""
    problems = []
    if missing:
        problems.append(f'{backend}: {len(missing)} corpus documents missing, e.g. {list(missing)[:3]}')
    if control != 1:
        problems.append(f'{backend}: {control} control records (expected 1)')
    problems += shape_problems(backend, shape, seeded_now)
    if expected_orphan is None or list(orphan_ids) != [expected_orphan]:
        problems.append(
            f'{backend}: documents without chunk 0 = {list(orphan_ids)} (expected exactly [{expected_orphan}])'
        )
    if documents != expected_documents:
        problems.append(f'{backend}: {documents} documents (expected {expected_documents})')
    if long_manual_chunks is None or long_manual_chunks < LONG_MANUAL_MIN_ROWS:
        problems.append(
            f'{backend}: the long manual has {long_manual_chunks} rows (expected at least {LONG_MANUAL_MIN_ROWS}: '
            'was it seeded by a chunker that ignores strlen?)'
        )
    if median_chunk_chars is None or not MEDIAN_CHARS[0] <= median_chunk_chars <= MEDIAN_CHARS[1]:
        problems.append(
            f'{backend}: median chunk of {median_chunk_chars} characters (expected {MEDIAN_CHARS[0]}-{MEDIAN_CHARS[1]:,})'
        )
    return problems


# ---------------------------------------------------------------------------
# Preflight: what the engine's chunker node would cut
# ---------------------------------------------------------------------------


class ChunkerRefused(RuntimeError):
    """The engine's chunker would not give the calibrated shape; nothing was created or dropped."""

    def __init__(self, preview: Dict[str, Any]) -> None:
        super().__init__('; '.join(preview.get('problems') or ['the chunker preflight failed']))
        self.preview = preview


def engine_chunker(executable: str = sys.executable) -> Path:
    """The chunker node file the engine imports.

    That is the ``nodes`` package first on this interpreter's path (run under
    the engine, which puts a checkout's ``nodes/src`` ahead of its own
    ``dist/server/nodes``), else the copy next to ``executable``, else the
    repository's. The package is located, never imported.
    """
    try:
        spec = importlib.util.find_spec('nodes')
    except (ImportError, ValueError):
        spec = None
    for location in (spec.submodule_search_locations or []) if spec else []:
        node = Path(location) / 'preprocessor_langchain' / 'langchain.py'
        if node.is_file():
            return node.resolve()
    copy = Path(executable).resolve().parent / 'nodes' / 'preprocessor_langchain' / 'langchain.py'
    return copy if copy.is_file() else REPO_CHUNKER


def template_strlen(keys: Sequence[str] = ('postgres', 'rocketride_vector', 'qdrant', 'chroma')) -> int:
    """The chunk length (``strlen``) of chunk_1 in the templates this seed starts (one value for all)."""
    lengths = set()
    for key in keys:
        (chunker,) = [c for c in fx.load_template(fx.FIXTURES[key].template)['components'] if c['id'] == 'chunk_1']
        config = chunker['config']
        lengths.add(int(config[config.get('profile', 'default')]['strlen']))
    if len(lengths) != 1:
        raise RuntimeError(f'the templates disagree on the chunk length: {sorted(lengths)}')
    return lengths.pop()


def corpus_texts() -> Dict[str, str]:
    """The demo corpus, by relative path."""
    return dict(_corpus().build_corpus())


def chunker_preview(texts: Dict[str, str], strlen: int, node_source: str) -> Dict[str, Any]:
    """What the chunker node in ``node_source`` cuts from ``texts`` with ``strlen``.

    The node's own keyword filter (``calibrate_chunking.node_splitter_kwargs``)
    is applied to the arguments it builds for LangChain's splitter, so the
    answer follows the node's code; the texts are the corpus files as written
    (the parser hands text and markdown through unchanged).
    """
    import langchain_text_splitters

    kept = cal.node_splitter_kwargs({'chunk_size': strlen, 'chunk_overlap': 0, 'length_function': len}, node_source)
    splitter = langchain_text_splitters.RecursiveCharacterTextSplitter(**kept)
    chunks = {rel: splitter.split_text(text) for rel, text in texts.items()}
    return {
        'strlen': strlen,
        'passes_chunk_size': 'chunk_size' in kept,
        'long_manual_chunks': len(chunks.get(ORPHAN_REL, [])),
        'median_chunk_chars': median_length([c for parts in chunks.values() for c in parts]),
    }


def chunking_problems(preview: Dict[str, Any]) -> List[str]:
    """Why ``preview`` would not seed the calibrated shape (empty when it would)."""
    problems = []
    rows = preview.get('long_manual_chunks')
    if rows is None or rows <= LONG_MANUAL_MIN_ROWS:
        problems.append(
            f'the chunker would cut the long manual into {rows} chunks (more than {LONG_MANUAL_MIN_ROWS} needed, '
            'so at least that many rows stay once chunk 0 is deleted)'
        )
    median = preview.get('median_chunk_chars')
    if median is None or not MEDIAN_CHARS[0] <= median <= MEDIAN_CHARS[1]:
        problems.append(
            f'the chunker would give a median chunk of {median} characters (expected {MEDIAN_CHARS[0]}-{MEDIAN_CHARS[1]:,})'
        )
    return problems


def chunker_check() -> Dict[str, Any]:
    """Preview the engine's chunker on the corpus with the templates' length; ``problems`` says what is wrong."""
    node = engine_chunker()
    preview = chunker_preview(corpus_texts(), template_strlen(), node.read_text(encoding='utf-8'))
    preview['node'] = str(node)
    preview['problems'] = chunking_problems(preview)
    if not preview['passes_chunk_size']:
        preview['problems'].append(f'{node} drops chunk_size: its splitter keeps its own 4,000-character default')
    return preview


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
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        columns = sorted(r[0] for r in cur.fetchall())
        meta_rows = 0
        if 'meta' in columns:
            cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE objectid <> 'schema' AND meta IS NOT NULL").format(t))
            meta_rows = cur.fetchone()[0]
        cur.execute(
            sql.SQL(
                "SELECT objectid FROM {} WHERE objectid <> 'schema' GROUP BY objectid HAVING NOT bool_or(chunkid = 0) ORDER BY objectid"
            ).format(t)
        )
        orphan_ids = [r[0] for r in cur.fetchall()]
        cur.execute(sql.SQL("SELECT objectid, count(*) FROM {} WHERE objectid <> 'schema' GROUP BY objectid").format(t))
        counts = dict(cur.fetchall())
        cur.execute(sql.SQL("SELECT content FROM {} WHERE objectid <> 'schema'").format(t))
        contents = [r[0] or '' for r in cur.fetchall()]
    return {
        'control': control,
        'meta_column': 'meta' in columns,
        'shape': {'columns': columns, 'rows': len(contents), 'meta_rows': meta_rows},
        'orphans': orphan_ids,
        'documents': len(counts),
        'chunks': sum(counts.values()),
        'object_ids': set(counts),
        'counts': counts,
        'median_chunk_chars': median_length(contents),
    }


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(host=fx.QDRANT['host'], port=fx.QDRANT['port'], timeout=30)


def _qdrant_records(collection: str) -> List[Tuple[Any, Dict[str, Any]]]:
    """(point id, payload) of every point."""
    client = _qdrant()
    out, offset = [], None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False
        )
        out.extend((p.id, p.payload or {}) for p in points)
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


def _row_facts(rows: Sequence[Tuple[str, int, str]]) -> Dict[str, Any]:
    """Facts from (objectId, chunkId, content) rows of a whole collection."""
    keys = [(o, c) for o, c, _ in rows]
    counts = collections.Counter(o for o, _ in keys if o != 'schema')
    return {
        'control': sum(1 for o, _ in keys if o == 'schema'),
        'orphans': orphans(keys),
        'documents': len(counts),
        'chunks': sum(counts.values()),
        'object_ids': set(counts),
        'counts': dict(counts),
        'median_chunk_chars': median_length([t for o, _, t in rows if o != 'schema']),
    }


def qdrant_facts(collection: str) -> Dict[str, Any]:
    records = [(pid, payload.get('meta') or {}, payload) for pid, payload in _qdrant_records(collection)]
    facts = _row_facts([(m.get('objectId'), m.get('chunkId') or 0, p.get('content') or '') for _, m, p in records])
    facts['shape'] = point_shape((pid, m, p.keys()) for pid, m, p in records)
    return facts


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


def _chroma_records(collection: str) -> List[Tuple[str, Dict[str, Any], str]]:
    """(id, metadata, document) of every record."""
    got = _chroma().get_collection(collection).get(include=['metadatas', 'documents'])
    return [
        (rid, meta or {}, doc or '')
        for rid, meta, doc in zip(got['ids'], got['metadatas'] or [], got['documents'] or [])
    ]


def chroma_plant_orphan(collection: str, object_id: str) -> None:
    _chroma().get_collection(collection).delete(where={'$and': [{'objectId': object_id}, {'chunkId': 0}]})


def chroma_facts(collection: str) -> Dict[str, Any]:
    records = _chroma_records(collection)
    facts = _row_facts([(m.get('objectId'), m.get('chunkId') or 0, text) for _, m, text in records])
    facts['shape'] = point_shape((rid, m, ()) for rid, m, _ in records)
    return facts


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
    """Seed the selected backends that are missing (or all of them with --recreate).

    Raises ChunkerRefused, before anything is created or dropped, when the
    engine's chunker would not give the calibrated shape.
    """
    exists = {'pgvector': pg_exists, 'qdrant': qdrant_exists, 'chroma': chroma_exists}
    todo = [b for b in BACKENDS if b in backends and (recreate or not exists[b](LEGACY))]
    if not todo:
        return {}
    preview = chunker_check()
    if preview['problems']:
        raise ChunkerRefused(preview)

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
            if 'pgvector' in todo:
                pg_create(LEGACY, recreate)
                await ingest(client, 'postgres', LEGACY, files)
                await ingest(client, 'rocketride_vector', LEGACY, rr_files)
                kept = pg_chunk_ids(LEGACY, orphan_id)
                notes['pgvector'] = {
                    'long_manual_chunks': len(kept),
                    'long_manual_kept_chunk0': bool(kept) and kept[0] == 0,
                    'planted_rows': pg_plant_orphan(LEGACY, orphan_id),
                }
            if 'qdrant' in todo:
                if recreate:
                    qdrant_drop(LEGACY)
                await ingest(client, 'qdrant', LEGACY, files)
                qdrant_plant_orphan(LEGACY, orphan_id)
                notes['qdrant'] = {'seeded': True}
            if 'chroma' in todo:
                if recreate:
                    chroma_drop(LEGACY)
                await ingest(client, 'chroma', LEGACY, files)
                chroma_plant_orphan(LEGACY, orphan_id)
                notes['chroma'] = {'seeded': True}
    for note in notes.values():
        note['chunker'] = {k: preview[k] for k in ('node', 'strlen', 'long_manual_chunks', 'median_chunk_chars')}
    return notes


def verify(backends: Sequence[str], seeded_now: Sequence[str] = ()) -> Tuple[Dict[str, Any], List[str]]:
    """Facts and problems for every selected backend (``seeded_now``: the backends this run seeded).

    A ``meta`` column on pgvector is a problem only right after this run seeded
    the table: a newer driver adds the column when it first opens the table.
    """
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
        f['long_manual_chunks'] = f.pop('counts').get(orphan_id, 0)
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
            long_manual_chunks=f['long_manual_chunks'],
            median_chunk_chars=f['median_chunk_chars'],
            shape=f.get('shape'),
            seeded_now=backend in seeded_now,
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
    try:
        notes = {} if args.verify_only else asyncio.run(seed(backends, args.recreate))
    except ChunkerRefused as refused:
        print(json.dumps({'seeded': {}, 'refused': refused.preview}, indent=2, default=str))
        return 1
    facts, problems = verify(backends, seeded_now=list(notes))
    print(json.dumps({'seeded': notes, 'facts': facts, 'problems': problems}, indent=2, default=str))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
