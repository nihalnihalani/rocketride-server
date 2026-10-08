# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""The shipped Vector Explorer templates, started in a real engine and called through the SDK.

The store suites load the drivers directly (or behind mocks), so none of them
shows that the engine starts the templates in ``apps/vector-ui/templates``,
routes a tool call by node id from a source's task token, stamps the caller on
it, or that a write is refused by the gate end to end. This suite does,
unmocked:

1. It starts the engine (``dist/server/engine ai/eaas.py``) without
   ``ROCKETRIDE_MOCK``, with its own API key and store, a stand-in for the
   cloud database broker (an HTTP server in this process that answers
   ``/provision`` with the pgvector test database's DSN for one per-run token)
   and the local LLM test stub (``scripts/acceptance/vector-explorer/stub_llm.py``,
   in this process; its answers start with ``[STUB-LLM]``; it is not a model).
2. For each supported template (pgvector, RocketRide Vector, Qdrant, Chroma)
   it keeps the template's pipeline and changes only what points at a server
   (connection settings, a per-run collection name) and the LLM (the stub). It
   starts all three sources (``tools_1``, ``chat_1``, ``ingest_1``), uploads a
   few documents of the demo corpus through ``ingest_1`` and checks what
   reached the database through an independent admin connection.
3. It builds a legacy-shaped copy of that collection (the shape the store
   drivers wrote before the explorer: random point ids, no file size or ingest
   time, no ``meta`` column on pgvector, one document without chunk 0) and
   starts the template a second time on it. ``RR_TEST_VECTOR_LEGACY=seeded``
   uses the collections ``seed_legacy.sh`` wrote (``vx_legacy_docs``) instead;
   the suite then only adds and removes documents of its own there.
4. Every explorer tool is called by name through ``client.tool`` on the
   template's node ids, on the new and the legacy collection: dialect, stats,
   documents, chunks, vectors, sample, project, neighbors, search,
   remove_document, the legacy get/objdir/delete/upsert, and ``embed`` on
   ``embed_1``. Writes are refused through the chat and ingest tokens, on
   ``store_2``, as a broadcast, with the switch off and for the control record;
   the expectation for the switch reads ``VECTOR_ALLOW_WRITES_DEFAULT``.
5. A chat through ``chat_1`` returns the stub's answer and the retrieved chunks;
   a pipeline shaped like the repository's RAG example (webhook and chat, no
   Tools source) answers ``dialect``/``stats`` through its chat token and
   refuses ``remove_document`` with ``WRITES_SOURCE``; ``rocketride_vector.pipe``
   runs again with the broker answering the transaction-mode pooler's DSN
   (``RR_TEST_PGVECTOR_POOLER_DSN``) and a search filtered to one document
   still returns ``k`` rows.
6. No answer carries a host, DSN, credential, database name or token.

Services (the defaults are the local containers of
``scripts/acceptance/vector-explorer/README.md``):

    RR_TEST_PGVECTOR_DSN         postgres.pipe, rocketride_vector.pipe, the stock-RAG shape
    RR_TEST_PGVECTOR_POOLER_DSN  the pooled rocketride_vector pass (unset: that test is NOT RUN)
    RR_TEST_QDRANT_URL           qdrant.pipe
    RR_TEST_CHROMA_URL           chroma.pipe

A service that is unreachable skips its template unless ``RR_REQUIRE_DB_TESTS``
is set, which turns it into a failure. Optional: ``RR_TEST_TOOLPATH_ENGINE_PORT``
fixes the engine's port (default: a free one).

Tests marked ``NEEDS:`` exercise code of other Vector Explorer lanes that is
not on this branch; the integration step removes each mark when that lane is
merged, and a NEEDS skip is never a pass.
"""

from __future__ import annotations

import asyncio
import collections
import importlib.util
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SERVER_DIR = _REPO / 'dist' / 'server'
_ENGINE = _SERVER_DIR / ('engine.exe' if sys.platform == 'win32' else 'engine')
_TEMPLATES = _REPO / 'apps' / 'vector-ui' / 'templates'
_ACC = _REPO / 'scripts' / 'acceptance' / 'vector-explorer'
_STORE = _REPO / 'packages' / 'ai' / 'src' / 'ai' / 'common' / 'store'

_DB_TESTS_REQUIRED = bool(os.environ.get('RR_REQUIRE_DB_TESTS'))

if _DB_TESTS_REQUIRED:
    from rocketride import CommandException, RocketRideClient
    from rocketride.schema import Question
else:
    _sdk = pytest.importorskip('rocketride')
    CommandException, RocketRideClient = _sdk.CommandException, _sdk.RocketRideClient
    Question = pytest.importorskip('rocketride.schema').Question

if not _ENGINE.exists():
    if _DB_TESTS_REQUIRED:
        pytest.fail(f'RR_REQUIRE_DB_TESTS is set but there is no engine at {_ENGINE}', pytrace=False)
    pytest.skip(f'no engine at {_ENGINE} (run: builder server:build)', allow_module_level=True)


def _load(name: str, path: Path):
    """Import one file by path (the store package's __init__ pulls in the engine)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# One source of truth for the write default and the limits (the node reads the same file).
vx_defaults = _load('vx_toolpath_defaults', _STORE / 'vx_defaults.py')
vx_types = _load('vx_toolpath_types', _STORE / 'vx_types.py')
gen_corpus = _load('vx_toolpath_corpus', _ACC / 'demo' / 'gen_corpus.py')
stub_llm = _load('vx_toolpath_stub_llm', _ACC / 'stub_llm.py')

# ---------------------------------------------------------------------------
# Cross-lane code this suite exercises that is not on this branch. The
# integration step deletes each mark (or table entry) when the lane is merged.
# ---------------------------------------------------------------------------

NEEDS_TOOLS = 'NEEDS:L0,L1 merged — integration gate G2'  # explorer tools, call context, write gate
NEEDS_EMBED = 'NEEDS:L0,L1,L5 merged — integration gate G2'  # embed on embed_1 (+ the tools that use it)
NEEDS_STOCK_RAG = 'NEEDS:L0,L1,L2 merged — integration gate G2'
NEEDS_POOLER = 'NEEDS:L1,L2 merged — integration gate G2'
needs_tools = pytest.mark.skip(reason=NEEDS_TOOLS)
needs_embed = pytest.mark.skip(reason=NEEDS_EMBED)
# The Chroma driver before L3 filters objdir on a key it never writes ('chunk'), so it lists nothing.
OBJDIR_NEEDS = {'chroma': 'NEEDS:L3 merged — integration gate G2'}
# The pgvector drivers before L2 cannot create a table (their DDL lacks the signature column
# their insert writes), so neither pgvector template can ingest into a new collection.
TEMPLATE_NEEDS = {
    'postgres': 'NEEDS:L2 merged — integration gate G2',
    'rocketride_vector': 'NEEDS:L2 merged — integration gate G2',
}

SUPPORTED = ('postgres', 'rocketride_vector', 'qdrant', 'chroma')
PROVIDER_BACKEND = {'postgres': 'pgvector', 'rocketride_vector': 'pgvector', 'qdrant': 'qdrant', 'chroma': 'chroma'}
EMBEDDING_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
DIMENSION = 384

RUN = uuid.uuid4().hex[:8]
NEW_COLLECTION = f'vx_tp_{RUN}'
LEGACY_COLLECTION = f'vx_tp_{RUN}_legacy'
SEEDED_LEGACY = 'vx_legacy_docs'
LEGACY_MODE = os.environ.get('RR_TEST_VECTOR_LEGACY', 'emulated').strip().lower() or 'emulated'

ENGINE_START_S = 180
USE_TIMEOUT_S = 300
TOOL_TIMEOUT_MS = 90_000

# The documents every run uploads (demo corpus paths) and the upload names they get.
UPLOAD_PREFIX = f'C:/tp-{RUN}/'
CORPUS_DOCS = (
    'handbooks/falcon_handbook.md',
    'field/kestrel_field_guide.md',
    'greenhouse/orchid_notes.txt',
    'ops/memo_q3.txt',
    'observatory/telescope_calibration.md',
    'kitchen/winter_stew.md',
    'tables/equipment_inventory.html',
    'scans/ocr_scan_0417.txt',
)
# The multi-chunk document; on the emulated legacy collection it loses chunk 0.
MULTI_DOC = 'handbooks/falcon_handbook.md'
WATER_QUESTION = 'Where does Falcon Station get its drinking water?'
UNRELATED_QUESTION = 'Lattice regularisation of quantum chromodynamics at finite temperature'

# Keys whose values are document text; the secrets scan skips them.
CONTENT_KEYS = frozenset({'content', 'page_content', 'snip', 'preview', 'text', 'answers', 'answer'})


def object_id(name: str) -> str:
    """The objectId the engine derives for an upload named ``name``."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'null://Stream/' + name))


def stored_path(name: str) -> str:
    """The path a store keeps for an upload name (the engine drops a leading slash)."""
    return name.lstrip('/')


# ---------------------------------------------------------------------------
# Services: an independent admin connection per database, never via the node
# ---------------------------------------------------------------------------


def _guard(collection: str) -> str:
    """Only this suite's collections are ever dropped."""
    if not collection.startswith('vx_tp_'):
        raise ValueError(f'refusing to drop {collection!r}: not a vx_tp_ collection')
    return collection


LEGACY_META_KEYS = (
    'objectId',
    'chunkId',
    'nodeId',
    'parent',
    'permissionId',
    'isDeleted',
    'isTable',
    'tableId',
    'signature',
)


class _PgVector:
    """postgres.pipe (direct settings) and rocketride_vector.pipe (DSN from the broker stand-in)."""

    backend = 'pgvector'

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.dsn = os.environ.get('RR_TEST_PGVECTOR_DSN', 'postgresql://rruser:rrpass@127.0.0.1:55432/rrtenant')
        self.pooler_dsn = os.environ.get('RR_TEST_PGVECTOR_POOLER_DSN', '').strip()
        url = urlparse(self.dsn)
        self.host, self.port = url.hostname or '127.0.0.1', url.port or 5432
        self.user, self.password = url.username or '', url.password or ''
        self.database = (url.path or '/').lstrip('/')
        self.where = f'{self.host}:{self.port}'

    def secrets(self) -> List[str]:
        out = ['postgresql://', 'postgres://', self.where, self.database]
        if self.password:
            out.append(self.password)
        if self.pooler_dsn:
            pooler = urlparse(self.pooler_dsn)
            out += [f'{pooler.hostname}:{pooler.port}', pooler.password or '']
        return [s for s in out if s]

    def _connect(self):
        import psycopg2

        conn = psycopg2.connect(self.dsn, connect_timeout=5)
        conn.autocommit = True
        return conn

    def _sql(self, statement, params=()) -> List[tuple]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(statement, params or None)
                return cur.fetchall() if cur.description else []
        finally:
            conn.close()

    def unavailable(self) -> Optional[str]:
        try:
            self._connect().close()
        except Exception as e:  # noqa: BLE001 - reported as the reason
            return f'the pgvector test database is not reachable at {self.where} ({type(e).__name__})'
        return None

    def broker_dsn(self, dsn: Optional[str] = None) -> str:
        dsn = dsn or self.dsn
        # The engine requires TLS on a broker DSN unless every host is loopback and the DSN says so.
        return dsn if 'sslmode=' in dsn else dsn + ('&' if '?' in dsn else '?') + 'sslmode=disable'

    def overrides(self, collection: str) -> Dict[str, Any]:
        if self.provider == 'rocketride_vector':
            return {'collection': collection}
        return {
            'host': self.host,
            'port': self.port,
            'user': self.user,
            'password': self.password,
            'database': self.database,
            'collection': collection,
        }

    def exists(self, collection: str) -> bool:
        return bool(self._sql('SELECT to_regclass(%s) IS NOT NULL', (f'public.{collection}',))[0][0])

    def counts(self, collection: str) -> Dict[str, int]:
        from psycopg2 import sql

        rows = self._sql(
            sql.SQL("SELECT objectid, count(*) FROM {} WHERE objectid <> 'schema' GROUP BY objectid").format(
                sql.Identifier(collection)
            )
        )
        return {o: int(n) for o, n in rows}

    def chunk_ids(self, collection: str, oid: str) -> List[int]:
        from psycopg2 import sql

        q = sql.SQL('SELECT chunkid FROM {} WHERE objectid = %s ORDER BY chunkid').format(sql.Identifier(collection))
        return [r[0] for r in self._sql(q, (oid,))]

    def vector(self, collection: str, oid: str, chunk: int) -> List[float]:
        from psycopg2 import sql

        q = sql.SQL('SELECT embedding::text FROM {} WHERE objectid = %s AND chunkid = %s').format(
            sql.Identifier(collection)
        )
        (text,) = self._sql(q, (oid, chunk))[0]
        return [float(x) for x in text.strip('[]').split(',')]

    def make_legacy(self, src: str, dst: str, orphan: str) -> None:
        """Copy src into dst in the shape the old drivers wrote (old DDL + signature, serial ids, no meta), orphan without chunk 0."""
        from psycopg2 import sql

        wanted = (
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
        have = {
            r[0] for r in self._sql('SELECT column_name FROM information_schema.columns WHERE table_name = %s', (src,))
        }
        # A column the new table does not have (the driver may keep it in meta) is copied as NULL.
        cols = ', '.join(wanted)
        select = ', '.join(c if c in have else 'NULL' for c in wanted)
        self.drop(dst)
        self._sql(
            sql.SQL(
                'CREATE TABLE {} (id bigserial PRIMARY KEY, content text, objectId text, nodeId text, parent text, '
                'permissionId int, isDeleted boolean, chunkId int, isTable boolean, tableId int, vectorSize int, '
                'modelName text, embedding vector({}), signature text)'
            ).format(sql.Identifier(dst), sql.Literal(DIMENSION))
        )
        self._sql(
            sql.SQL('INSERT INTO {} (' + cols + ') SELECT ' + select + ' FROM {} ORDER BY id').format(
                sql.Identifier(dst), sql.Identifier(src)
            )
        )
        self.delete_chunk0(dst, orphan)

    def delete_chunk0(self, collection: str, oid: str) -> None:
        from psycopg2 import sql

        self._sql(
            sql.SQL('DELETE FROM {} WHERE objectid = %s AND chunkid = 0').format(sql.Identifier(collection)), (oid,)
        )

    def drop(self, collection: str) -> None:
        from psycopg2 import sql

        self._sql(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(_guard(collection))))


class _Qdrant:
    """qdrant.pipe against the Qdrant test server."""

    backend = 'qdrant'
    provider = 'qdrant'

    def __init__(self) -> None:
        url = urlparse(os.environ.get('RR_TEST_QDRANT_URL', 'http://127.0.0.1:56333'))
        self.host, self.port = url.hostname or '127.0.0.1', url.port or 6333
        self.where = f'{self.host}:{self.port}'

    def secrets(self) -> List[str]:
        return [self.where, f'http://{self.where}']

    def client(self):
        from qdrant_client import QdrantClient

        return QdrantClient(host=self.host, port=self.port, timeout=30)

    def unavailable(self) -> Optional[str]:
        try:
            self.client().get_collections()
        except Exception as e:  # noqa: BLE001 - reported as the reason
            return f'Qdrant is not reachable at {self.where} ({type(e).__name__})'
        return None

    def overrides(self, collection: str) -> Dict[str, Any]:
        return {'host': self.host, 'port': self.port, 'collection': collection}

    def exists(self, collection: str) -> bool:
        return self.client().collection_exists(collection)

    def _points(self, collection: str, vectors: bool = False) -> list:
        client, out, offset = self.client(), [], None
        while True:
            points, offset = client.scroll(
                collection, limit=1000, offset=offset, with_payload=True, with_vectors=vectors
            )
            out += points
            if offset is None:
                return out

    def counts(self, collection: str) -> Dict[str, int]:
        out: Dict[str, int] = collections.Counter()
        for p in self._points(collection):
            oid = ((p.payload or {}).get('meta') or {}).get('objectId')
            if oid != 'schema':
                out[oid] += 1
        return dict(out)

    def chunk_ids(self, collection: str, oid: str) -> List[int]:
        metas = [((p.payload or {}).get('meta') or {}) for p in self._points(collection)]
        return sorted(int(m.get('chunkId') or 0) for m in metas if m.get('objectId') == oid)

    def vector(self, collection: str, oid: str, chunk: int) -> List[float]:
        for p in self._points(collection, vectors=True):
            m = (p.payload or {}).get('meta') or {}
            if m.get('objectId') == oid and int(m.get('chunkId') or 0) == chunk:
                return list(p.vector)
        raise KeyError((oid, chunk))

    def make_legacy(self, src: str, dst: str, orphan: str) -> None:
        """Copy src into dst as the old driver wrote it: uuid4 ids, payload {content, meta} with the old keys only."""
        from qdrant_client import models

        client = self.client()
        self.drop(dst)
        client.create_collection(
            dst, vectors_config=models.VectorParams(size=DIMENSION, distance=models.Distance.COSINE)
        )
        for key in ('meta.nodeId', 'meta.objectId', 'meta.parent'):
            client.create_payload_index(dst, field_name=key, field_schema=models.PayloadSchemaType.KEYWORD)
        for key in ('meta.permissionId', 'meta.chunkId', 'meta.tableId'):
            client.create_payload_index(dst, field_name=key, field_schema=models.PayloadSchemaType.INTEGER)
        for key in ('meta.isDeleted', 'meta.isTable'):
            client.create_payload_index(dst, field_name=key, field_schema=models.PayloadSchemaType.BOOL)
        points = []
        for p in self._points(src, vectors=True):
            meta = dict((p.payload or {}).get('meta') or {})
            keep = LEGACY_META_KEYS + (('vectorSize', 'modelName') if meta.get('objectId') == 'schema' else ())
            payload = {
                'content': (p.payload or {}).get('content', ''),
                'meta': {k: meta.get(k) for k in keep if k in meta},
            }
            points.append(models.PointStruct(id=str(uuid.uuid4()), vector=list(p.vector), payload=payload))
        client.upsert(dst, points=points, wait=True)
        self.delete_chunk0(dst, orphan)

    def delete_chunk0(self, collection: str, oid: str) -> None:
        from qdrant_client import models

        self.client().delete(
            collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(key='meta.objectId', match=models.MatchValue(value=oid)),
                        models.FieldCondition(key='meta.chunkId', match=models.MatchValue(value=0)),
                    ]
                )
            ),
            wait=True,
        )

    def drop(self, collection: str) -> None:
        client = self.client()
        if client.collection_exists(_guard(collection)):
            client.delete_collection(collection)


class _Chroma:
    """chroma.pipe against the Chroma test server."""

    backend = 'chroma'
    provider = 'chroma'

    def __init__(self) -> None:
        url = urlparse(os.environ.get('RR_TEST_CHROMA_URL', 'http://127.0.0.1:58000'))
        self.host, self.port = url.hostname or '127.0.0.1', url.port or 8000
        self.where = f'{self.host}:{self.port}'

    def secrets(self) -> List[str]:
        return [self.where, f'http://{self.where}']

    def client(self):
        import chromadb

        return chromadb.HttpClient(host=self.host, port=self.port)

    def unavailable(self) -> Optional[str]:
        try:
            self.client().heartbeat()
        except Exception as e:  # noqa: BLE001 - reported as the reason
            return f'Chroma is not reachable at {self.where} ({type(e).__name__})'
        return None

    def overrides(self, collection: str) -> Dict[str, Any]:
        return {'host': self.host, 'port': str(self.port), 'collection': collection}

    def exists(self, collection: str) -> bool:
        return collection in {c if isinstance(c, str) else c.name for c in self.client().list_collections()}

    def _get(self, collection: str, include: Sequence[str]) -> Dict[str, Any]:
        return self.client().get_collection(collection).get(include=list(include))

    def counts(self, collection: str) -> Dict[str, int]:
        out: Dict[str, int] = collections.Counter()
        for m in self._get(collection, ['metadatas'])['metadatas'] or []:
            if m.get('objectId') != 'schema':
                out[m.get('objectId')] += 1
        return dict(out)

    def chunk_ids(self, collection: str, oid: str) -> List[int]:
        metas = self._get(collection, ['metadatas'])['metadatas'] or []
        return sorted(int(m.get('chunkId') or 0) for m in metas if m.get('objectId') == oid)

    def vector(self, collection: str, oid: str, chunk: int) -> List[float]:
        got = self._get(collection, ['metadatas', 'embeddings'])
        for m, v in zip(got['metadatas'], got['embeddings']):
            if m.get('objectId') == oid and int(m.get('chunkId') or 0) == chunk:
                return [float(x) for x in v]
        raise KeyError((oid, chunk))

    def make_legacy(self, src: str, dst: str, orphan: str) -> None:
        """Copy src into dst as the old driver wrote it: uuid4 ids, flat metadata with the old keys only."""
        got = self._get(src, ['metadatas', 'embeddings', 'documents'])
        self.drop(dst)
        target = self.client().create_collection(dst, metadata={'hnsw:space': 'cosine'})
        metas = []
        for m in got['metadatas']:
            keep = LEGACY_META_KEYS + (('vectorSize', 'modelName') if m.get('objectId') == 'schema' else ())
            metas.append({k: m[k] for k in keep if m.get(k) is not None})
        target.add(
            ids=[str(uuid.uuid4()) for _ in metas],
            embeddings=[[float(x) for x in v] for v in got['embeddings']],
            metadatas=metas,
            documents=list(got['documents']),
        )
        self.delete_chunk0(dst, orphan)

    def delete_chunk0(self, collection: str, oid: str) -> None:
        self.client().get_collection(collection).delete(where={'$and': [{'objectId': oid}, {'chunkId': 0}]})

    def drop(self, collection: str) -> None:
        if self.exists(_guard(collection)):
            self.client().delete_collection(collection)


def _service(provider: str):
    if provider in ('postgres', 'rocketride_vector'):
        return _PgVector(provider)
    return {'qdrant': _Qdrant, 'chroma': _Chroma}[provider]()


# ---------------------------------------------------------------------------
# The engine, the broker stand-in and the LLM test stub
# ---------------------------------------------------------------------------


class _Broker:
    """Answers the broker's POST /provision with the current DSN, for this run's token only."""

    def __init__(self, dsn: str) -> None:
        self.token = f'toolpath-broker-{secrets.token_hex(12)}'
        self.dsn = dsn
        self.tenants: List[str] = []
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}')
                if self.headers.get('Authorization') != f'Bearer {broker.token}':
                    self.send_response(401)
                    self.end_headers()
                    return
                broker.tenants.append(body.get('tenant_id'))
                payload = json.dumps({'dsn': broker.dsn, 'database': 'test', 'role': 'test', 'created': False}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self._server.server_port}/provision'
        threading.Thread(target=self._server.serve_forever, name='toolpath-broker', daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class _Stub:
    """The LLM test stub (scripts/acceptance/vector-explorer/stub_llm.py) on a free port in this process."""

    def __init__(self, log_dir: Path) -> None:
        self._server = stub_llm.StubServer(0, log_dir / 'stub_llm_requests.jsonl', '', '{}')
        self.url = f'http://127.0.0.1:{self._server.server_port}/v1'
        threading.Thread(target=self._server.serve_forever, name='toolpath-stub-llm', daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class _Engine:
    """``engine ai/eaas.py`` without mocks, plus one SDK client on a loop thread of its own."""

    def __init__(self, store_dir: Path, broker: _Broker) -> None:
        self.apikey = f'toolpath-{secrets.token_hex(12)}'
        env = {
            name: value
            for name, value in os.environ.items()
            if name.upper()
            not in (
                'ROCKETRIDE_MOCK',
                'ROCKETRIDE_DB_DSN',
                'ROCKETRIDE_DB_RESOLVE_ERROR',
                'ROCKETRIDE_DB_BROKER_URL',
                'ROCKETRIDE_DB_BROKER_TOKEN',
            )
        }
        env.update(
            {
                'ROCKETRIDE_APIKEY': self.apikey,
                'RR_STORE_URL': f'filesystem://{store_dir.as_posix()}',
                'RR_DB_BROKER_URL': broker.url,
                'RR_DB_BROKER_TOKEN': broker.token,
            }
        )
        port = int(os.environ.get('RR_TEST_TOOLPATH_ENGINE_PORT') or 0)
        self.output: collections.deque = collections.deque(maxlen=200)
        self._port: Optional[int] = None
        self._ready = threading.Event()
        # --autoterm: the engine exits when this process does (its stdin closes).
        self.proc = subprocess.Popen(
            [str(_ENGINE), '--autoterm', 'ai/eaas.py', '--host=127.0.0.1', f'--port={port}', '--base_port=44000'],
            cwd=str(_SERVER_DIR),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors='replace',
        )
        threading.Thread(target=self._read_output, name='toolpath-engine-output', daemon=True).start()
        deadline = time.monotonic() + ENGINE_START_S
        while not self._ready.wait(0.5):
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError(f'the engine did not start:\n{self.tail()}')
        self.uri = f'http://127.0.0.1:{self._port}'
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name='toolpath-sdk-loop', daemon=True).start()
        self.client = RocketRideClient(uri=self.uri, auth=self.apikey, request_timeout=USE_TIMEOUT_S * 1000)
        self.run(self.client.connect(), 60)

    def _read_output(self) -> None:
        port_re = re.compile(r'Uvicorn running on https?://[\w.\[\]:]+:(\d+)')
        started = False
        for line in self.proc.stdout:
            self.output.append(line.rstrip())
            match = port_re.search(line)
            if match and self._port is None:
                self._port = int(match.group(1))
            started = started or 'Application startup complete' in line
            if started and self._port is not None:
                self._ready.set()

    def tail(self) -> str:
        return '\n'.join(list(self.output)[-40:])

    def run(self, coro, timeout: float = USE_TIMEOUT_S) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        if getattr(self, 'loop', None) is not None:
            try:
                self.run(self.client.disconnect(), 15)
            except Exception:  # noqa: BLE001 - shutting down
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        try:
            self.proc.stdin.close()
        except Exception:  # noqa: BLE001 - shutting down
            pass
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)


# Every tool answer of the run, for the secrets scan: (template, side, tool, answer).
ANSWERS: List[Tuple[str, str, str, Any]] = []


@pytest.fixture(scope='module')
def broker():
    stand_in = _Broker(_PgVector('rocketride_vector').broker_dsn())
    yield stand_in
    stand_in.close()


@pytest.fixture(scope='module')
def stub(tmp_path_factory):
    server = _Stub(tmp_path_factory.mktemp('toolpath-stub'))
    yield server
    server.close()


@pytest.fixture(scope='module')
def engine(tmp_path_factory, broker):
    started = _Engine(tmp_path_factory.mktemp('toolpath-store'), broker)
    yield started
    started.stop()


@pytest.fixture(scope='module')
def corpus_files(tmp_path_factory):
    """The uploaded documents on disk: (path, upload name) in CORPUS_DOCS order."""
    root = tmp_path_factory.mktemp('toolpath-corpus')
    corpus = gen_corpus.build_corpus()
    out = []
    for rel in CORPUS_DOCS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(corpus[rel], encoding='utf-8')
        out.append((path, UPLOAD_PREFIX + rel))
    return out


# ---------------------------------------------------------------------------
# One running pipeline per template and collection kind
# ---------------------------------------------------------------------------


def _template(provider: str) -> Dict[str, Any]:
    raw = json.loads((_TEMPLATES / f'{provider}.pipe').read_text(encoding='utf-8'))
    return raw.get('pipeline', raw)


def _pipeline(
    provider: str, service, collection: str, stub_url: str, *, store_1: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """The template with only its server settings, collection, LLM and identity changed."""
    pipe = json.loads(json.dumps(_template(provider)))
    pipe['project_id'] = str(uuid.uuid4())
    pipe['name'] = f'vx-toolpath {provider} {collection}'
    for comp in pipe['components']:
        if comp['id'] in ('store_1', 'store_2'):
            profile = comp['config']['profile']
            comp['config'][profile].update(service.overrides(collection))
            if comp['id'] == 'store_1' and store_1 is not None:
                comp['config'][profile] = {**comp['config'][profile], **store_1}
                comp['config'][profile] = {k: v for k, v in comp['config'][profile].items() if v is not None}
        elif comp['id'] == 'llm_1':
            comp['name'] = 'Local stub LLM'
            comp['config']['custom'].update({'base_url': stub_url, 'apikey': 'local-stub-not-a-key'})
    return pipe


class _Side:
    """One running copy of a template on one collection: its tokens and how to call it."""

    def __init__(
        self, eng: _Engine, template: str, kind: str, collection: str, pipe: Dict[str, Any], sources: Sequence[str]
    ) -> None:
        self.engine, self.template, self.kind, self.collection, self.pipe = eng, template, kind, collection, pipe
        self.tokens: Dict[str, str] = {}
        for source in sources:
            # ttl=0: the engine must not stop an idle fixture during a long run.
            self.tokens[source] = eng.run(eng.client.use(pipeline=pipe, source=source, ttl=0))['token']
        self.documents: Dict[str, str] = {}  # upload name -> objectId of what this side should list
        self.orphan: Optional[str] = None
        self.multi: Optional[str] = None

    def tool(
        self,
        name: str,
        inp: Optional[Dict[str, Any]] = None,
        *,
        source: str = 'tools_1',
        node: str = 'store_1',
        timeout: int = TOOL_TIMEOUT_MS,
    ) -> Any:
        answer = self.engine.run(
            self.engine.client.tool(
                token=self.tokens[source], tool=name, node_id=node, input=inp or {}, timeout=timeout
            )
        )
        ANSWERS.append((self.template, self.kind, name, answer))
        return answer

    def ok(self, name: str, inp: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
        answer = self.tool(name, inp, **kw)
        assert isinstance(answer, dict) and answer.get('success') is True, (
            f'{self.template}/{self.kind} {name} {inp}: {answer}'
        )
        return answer

    def refused(self, name: str, inp: Optional[Dict[str, Any]] = None, **kw) -> str:
        answer = self.tool(name, inp, **kw)
        assert isinstance(answer, dict) and answer.get('success') is False, (
            f'{self.template}/{self.kind} {name} {inp} was not refused: {answer}'
        )
        assert answer.get('code') in vx_types.TOOL_CODES, answer
        return answer['code']

    def upload(self, files: Sequence[Tuple[Path, str]]) -> List[Dict[str, Any]]:
        results = []
        for path, name in files:
            (result,) = self.engine.run(
                self.engine.client.send_files([(str(path), {'name': name})], self.tokens['ingest_1'])
            )
            results.append(result)
        return results

    def chat(self, text: str) -> Dict[str, Any]:
        question = Question()
        question.addQuestion(text)
        return self.engine.run(self.engine.client.chat(token=self.tokens['chat_1'], question=question))

    def stop(self) -> None:
        for token in self.tokens.values():
            try:
                self.engine.run(self.engine.client.terminate(token), 60)
            except Exception:  # noqa: BLE001 - already stopped
                pass


@pytest.fixture(scope='module', params=SUPPORTED)
def deployment(request, corpus_files):
    """The template started on a new collection (with the corpus uploaded) and on a legacy one."""
    provider: str = request.param
    if provider in TEMPLATE_NEEDS:
        pytest.skip(TEMPLATE_NEEDS[provider])
    service = _service(provider)
    reason = service.unavailable()
    if reason:
        if _DB_TESTS_REQUIRED:
            pytest.fail(f'RR_REQUIRE_DB_TESTS is set but {reason}', pytrace=False)
        pytest.skip(reason)
    eng: _Engine = request.getfixturevalue('engine')
    stub_server: _Stub = request.getfixturevalue('stub')
    sources = ('tools_1', 'chat_1', 'ingest_1')
    sides: List[_Side] = []
    try:
        new = _Side(
            eng, provider, 'new', NEW_COLLECTION, _pipeline(provider, service, NEW_COLLECTION, stub_server.url), sources
        )
        sides.append(new)
        results = new.upload(corpus_files)
        new.upload_results = results
        new.documents = {name: object_id(name) for _, name in corpus_files}
        new.multi = object_id(UPLOAD_PREFIX + MULTI_DOC)

        if LEGACY_MODE == 'seeded':
            legacy_collection = SEEDED_LEGACY
            if not service.exists(legacy_collection):
                pytest.fail(
                    f'RR_TEST_VECTOR_LEGACY=seeded but {legacy_collection} does not exist (run seed_legacy.sh)',
                    pytrace=False,
                )
            names = ['/srv/legacy/' + rel for rel in gen_corpus.build_corpus()]
            legacy_docs = {name: object_id(name) for name in names}
            legacy_orphan = object_id('/srv/legacy/manuals/long_manual.md')
            legacy_multi = object_id('/srv/legacy/' + MULTI_DOC)
        else:
            legacy_collection = LEGACY_COLLECTION
            service.make_legacy(NEW_COLLECTION, legacy_collection, new.multi)
            legacy_docs = dict(new.documents)
            legacy_orphan = new.multi
            legacy_multi = object_id(UPLOAD_PREFIX + 'field/kestrel_field_guide.md')
        legacy = _Side(
            eng,
            provider,
            'legacy',
            legacy_collection,
            _pipeline(provider, service, legacy_collection, stub_server.url),
            sources,
        )
        sides.append(legacy)
        legacy.documents, legacy.orphan, legacy.multi = legacy_docs, legacy_orphan, legacy_multi
        yield SimpleNamespace(
            provider=provider, service=service, engine=eng, stub=stub_server, new=new, legacy=legacy, files=corpus_files
        )
    finally:
        for side in sides:
            side.stop()
        for collection in (NEW_COLLECTION, LEGACY_COLLECTION):
            try:
                service.drop(collection)
            except Exception:  # noqa: BLE001 - best-effort clean-up
                pass


@pytest.fixture(params=('new', 'legacy'))
def side(request, deployment) -> _Side:
    return getattr(deployment, request.param)


def _keys(value: Any) -> set:
    """Every dict key anywhere inside value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _numbers(value) -> List[float]:
    return [float(x) for x in value]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0)


# ---------------------------------------------------------------------------
# The template runs; what the old and new tools both answer
# ---------------------------------------------------------------------------


def test_the_engine_runs_the_template_with_its_three_sources(deployment):
    rows = deployment.engine.run(deployment.engine.client.get_tasks())
    for side_ in (deployment.new, deployment.legacy):
        started = {
            r.get('source') for r in rows if (r.get('pipeline') or {}).get('project_id') == side_.pipe['project_id']
        }
        assert started == {'tools_1', 'chat_1', 'ingest_1'}, (side_.kind, started)
    comps = {c['id']: c for c in _template(deployment.provider)['components']}
    s1, s2 = comps['store_1']['config'], comps['store_2']['config']
    assert s1[s1['profile']].get('allow_writes') is True, 'the template must turn writes on for store_1'
    assert s2[s2['profile']].get('allow_writes') in (False, None), 'store_2 must never allow writes'


def test_every_upload_completed_and_reached_the_database(deployment):
    new = deployment.new
    assert [r.get('action') for r in new.upload_results] == ['complete'] * len(CORPUS_DOCS), [
        (r.get('filepath'), r.get('error')) for r in new.upload_results if r.get('action') != 'complete'
    ]
    counts = deployment.service.counts(new.collection)
    assert set(counts) == set(new.documents.values()), 'the store does not hold exactly the uploaded documents'
    assert counts[new.multi] >= 2, 'the multi-chunk document has one chunk; the suite needs two or more'
    assert deployment.service.chunk_ids(new.collection, new.multi)[0] == 0


def test_the_legacy_collection_has_its_planted_gap(deployment):
    legacy = deployment.legacy
    counts = deployment.service.counts(legacy.collection)
    assert set(legacy.documents.values()) <= set(counts), 'documents are missing from the legacy collection'
    assert deployment.service.chunk_ids(legacy.collection, legacy.orphan)[:1] != [0], 'the orphan still has chunk 0'
    assert deployment.service.chunk_ids(legacy.collection, legacy.multi)[0] == 0


def test_legacy_tools_answer_with_their_legacy_keys(side, deployment):
    stats = side.ok('stats')
    assert {'count', 'model', 'vector_size'} <= set(stats)
    rows = sum(deployment.service.counts(side.collection).values())
    assert stats['count'] == rows + 1, 'stats.count is every row including the control record'
    assert stats['model'] == EMBEDDING_MODEL and stats['vector_size'] == DIMENSION
    got = side.ok('get', {'object_id': side.multi})
    assert sorted(c['metadata']['chunkId'] for c in got['chunks']) == deployment.service.chunk_ids(
        side.collection, side.multi
    )


def test_objdir_lists_every_document_with_a_first_chunk(side, deployment):
    if deployment.provider in OBJDIR_NEEDS:
        pytest.skip(OBJDIR_NEEDS[deployment.provider])
    paths = side.ok('objdir')['paths']
    assert 'schema' not in paths.values()
    for name, oid in side.documents.items():
        if oid != side.orphan:
            assert paths.get(stored_path(name)) == oid, f'objdir does not list {name}'


def test_chat_returns_the_stub_answer_and_the_retrieved_chunks(side, deployment):
    result = side.chat(WATER_QUESTION)
    answers = result.get('answers') or []
    assert answers and str(answers[0]).startswith('[STUB-LLM]'), answers
    documents = result.get('documents') or []
    assert documents, 'the chat returned no documents (response_documents on store_2)'
    known = set(deployment.service.counts(side.collection))
    assert all((d.get('metadata') or {}).get('objectId') in known for d in documents)
    # The stub quotes its prompt: the retrieved text reached the LLM node.
    assert any((d.get('page_content') or '')[:40] in str(answers[0]) for d in documents) or 'context_quote' in str(
        answers[0]
    )


# ---------------------------------------------------------------------------
# Explorer tools (CONTRACT section 4) through the tools token
# ---------------------------------------------------------------------------


@needs_tools
def test_dialect_describes_the_store(side, deployment):
    d = side.ok('dialect')
    assert (d['dialect'], d['contract']) == ('vector', 'vector/1')
    assert d['provider'] == deployment.provider and d['backend'] == PROVIDER_BACKEND[deployment.provider]
    assert d['collection'] == side.collection
    assert (d['metric'], d['model'], d['dimension']) == ('cosine', EMBEDDING_MODEL, DIMENSION)
    assert d['support'] in vx_types.SUPPORT_LEVELS
    assert d['allow_writes'] is True and d['agent_writes'] is vx_defaults.VECTOR_AGENT_WRITES_DEFAULT
    assert d['writes_scope'] == 'tools_source'
    assert set(d['write_tools']) == {'remove_document', 'delete', 'upsert'}
    assert set(vx_types.CAPABILITY_KEYS) <= set(d['capabilities'])
    assert d['capabilities']['search_vector'] is True and d['capabilities']['soft_delete'] is False
    assert d['capabilities']['knn_native'] is (deployment.provider == 'qdrant')
    assert d['limits'] == vx_defaults.VECTOR_TOOL_LIMITS
    health = d['health']
    assert health['collection_exists'] is True and health['control_record'] is True
    s2 = side.ok('dialect', node='store_2')
    assert s2['allow_writes'] is False, 'store_2 must report writes off'


@needs_tools
def test_stats_full_and_quick(side, deployment):
    counts = deployment.service.counts(side.collection)
    full = side.ok('stats', {'mode': 'full'})
    assert full['collection_exists'] is True
    orphans = 1 if side.kind == 'legacy' else 0
    caveats = set(full.get('caveats') or []) | set(side.ok('dialect').get('caveats') or [])
    # A store that counts documents by their first chunk does not count the one without it.
    by_first_chunk = 'documents_by_first_chunk' in caveats
    assert full['documents'] == len(counts) - (orphans if by_first_chunk else 0), (full['documents'], caveats)
    assert full['chunks'] == sum(counts.values())
    assert full['deleted_chunks'] == 0
    if full['documents_without_first_chunk'] is not None:
        assert full['documents_without_first_chunk'] == orphans
    assert (full['dimension'], full['metric']) == (DIMENSION, 'cosine')
    assert full['computed_at'] and full['counts_as_of']
    quick = side.ok('stats', {'mode': 'quick'})
    assert quick['count'] == full['count'] and quick['counts_as_of'] == full['counts_as_of']


def _all_documents(side_: _Side, limit: int = 3) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    items, cursor, last = [], None, {}
    for _ in range(100):
        last = side_.ok('documents', {'cursor': cursor, 'limit': limit, 'deleted': 'active', 'sort': 'path'})
        items += last['items']
        cursor = last['next_cursor']
        if cursor is None:
            break
    return items, last


@needs_tools
def test_documents_lists_every_document_once(side, deployment):
    items, last = _all_documents(side)
    counts = deployment.service.counts(side.collection)
    ids = [i['objectId'] for i in items]
    assert 'schema' not in ids
    if last['distinct']:
        assert len(ids) == len(set(ids))
    assert set(ids) == set(counts), 'documents does not list exactly what the database holds'
    for item in items:
        if last['counts_exact']:
            assert item['chunks'] == counts[item['objectId']]
        assert item['has_first_chunk'] is (item['objectId'] != side.orphan)
    by_id = {i['objectId']: i['path'] for i in items}
    for name, oid in side.documents.items():
        assert by_id[oid] == stored_path(name)
    if last['total'] is not None:
        assert last['total'] == len(counts)


@needs_tools
def test_chunks_page_in_order_and_never_carry_vectors(side, deployment):
    expected = deployment.service.chunk_ids(side.collection, side.multi)
    seen, after = [], -1
    while True:
        page = side.ok('chunks', {'object_id': side.multi, 'after_chunk': after, 'limit': 1, 'deleted': 'active'})
        for item in page['items']:
            assert not {'embedding', 'vector', 'values'} & set(item), item.keys()
            seen.append(item['chunkId'])
        if not page['has_more']:
            break
        after = page['next_after']
    assert seen == expected
    assert side.refused('chunks', {'object_id': 'schema'}) == 'NOT_FOUND'
    assert side.refused('chunks', {'object_id': str(uuid.uuid4())}) == 'NOT_FOUND'
    probe = side.ok('chunks', {'object_id': side.multi, 'limit': 1})
    assert len(probe['items']) == 1


@needs_tools
def test_vectors_returns_the_stored_vector_for_at_most_two_keys(side, deployment):
    stored = deployment.service.vector(side.collection, side.multi, 0)
    out = side.ok('vectors', {'keys': [[side.multi, 0]]})
    (item,) = out['items']
    assert item['key'] == [side.multi, 0] and item['dimension'] == DIMENSION
    assert _cosine(_numbers(item['values']), stored) > 0.9999
    assert out['model'] == EMBEDDING_MODEL
    too_many = [[side.multi, 0], [side.multi, 1], [side.multi, 2]]
    assert side.refused('vectors', {'keys': too_many}) in ('LIMIT_EXCEEDED', 'INVALID_INPUT')


@needs_tools
def test_sample_is_seeded_columnar_and_within_its_caps(side, deployment):
    rows = sum(deployment.service.counts(side.collection).values())
    one = side.ok('sample', {'n': 1000, 'seed': 7, 'mode': 'detailed', 'knn_k': 5})
    assert one['n'] == rows and one['of']['chunks'] == rows
    pts = one['points']
    for column in ('doc', 'chunk', 'x', 'y', 'len', 'snip'):
        assert len(pts[column]) == one['n'], column
    assert all(len(s) <= vx_defaults.VECTOR_TOOL_LIMITS['snippet_chars'] + 1 for s in pts['snip'])
    assert len(one['knn']['offsets_row']) == one['n'] + 1
    assert one['knn_source'] == ('native' if deployment.provider == 'qdrant' else 'node')
    assert one['metric'] == 'cosine' and one['dimension'] == DIMENSION
    again = side.ok('sample', {'n': 1000, 'seed': 7, 'mode': 'detailed', 'knn_k': 5})
    assert (again['points']['doc'], again['points']['chunk']) == (pts['doc'], pts['chunk'])
    light = side.ok('sample', {'n': 1000, 'seed': 7, 'mode': 'light', 'knn_k': 5})
    assert light['mode'] == 'light' and not light['points'].get('snip')
    big = side.tool('sample', {'n': vx_defaults.VECTOR_TOOL_LIMITS['sample_max'] + 1, 'mode': 'detailed'})
    assert big.get('success') is False or big.get('n') <= vx_defaults.VECTOR_TOOL_LIMITS['sample_max']


@needs_embed
def test_embed_project_neighbors_and_search(side, deployment):
    emb = side.ok('embed', {'texts': [WATER_QUESTION], 'kind': 'query'}, node='embed_1')
    (vector,) = emb['vectors']
    assert emb['dimension'] == DIMENSION and len(vector) == DIMENSION and emb['model'] == EMBEDDING_MODEL
    sample = side.ok('sample', {'n': 1000, 'seed': 3})
    projected = side.ok(
        'project', {'sample_id': sample['sample_id'], 'vector': vector, 'm': 5, 'with_similarities': True}
    )
    assert len(projected['items'][0]['neighbors']) == 5 and len(projected['similarities']) == sample['n']
    near = side.ok('neighbors', {'key': [side.multi, 0], 'k': 3, 'exclude_self': True})
    sims = [i['sim'] for i in near['items']]
    assert len(near['items']) == 3 and sims == sorted(sims, reverse=True)
    assert [side.multi, 0] not in [i['key'] for i in near['items']]
    found = side.ok('search', {'vector': vector, 'top_k': 3})
    scores = [r['score'] for r in found['results']]
    assert scores == sorted(scores, reverse=True)
    # The water question's best chunk is the Falcon handbook's water section.
    falcon = {oid for name, oid in side.documents.items() if 'falcon_handbook' in name or 'long_manual' in name}
    assert any(r['metadata']['objectId'] in falcon for r in found['results']), found['results']
    assert side.refused('search', {'vector': vector[:10], 'top_k': 3}) == 'DIMENSION_MISMATCH'


@needs_embed
def test_search_returns_below_floor_rows_only_when_asked(side):
    (vector,) = side.ok('embed', {'texts': [UNRELATED_QUESTION], 'kind': 'query'}, node='embed_1')['vectors']
    plain = side.ok('search', {'vector': vector, 'top_k': 5})
    assert not any(r.get('below_floor') for r in plain['results'])
    wide = side.ok(
        'search', {'vector': vector, 'top_k': 5, 'include_below_floor': True, 'include_below_threshold': True}
    )
    below = [r for r in wide['results'] if r.get('below_floor')]
    assert below and all(r['score'] < 0.2 for r in below), wide['results']
    for row in wide['results']:
        assert {'raw_score', 'sim', 'below_threshold', 'below_floor'} <= set(row)


@needs_tools
def test_a_text_query_without_an_embedder_on_the_store_is_refused(side):
    assert side.refused('search', {'query': WATER_QUESTION}) == 'NO_EMBEDDER'


# ---------------------------------------------------------------------------
# Writes: the gate end to end (CONTRACT section 6)
# ---------------------------------------------------------------------------


def _own_document(side_: _Side, label: str, tmp_dir: Path) -> Tuple[str, str]:
    """Upload a small document of this test's own; (upload name, objectId)."""
    name = f'{UPLOAD_PREFIX}writes/{label}.md'
    path = tmp_dir / f'{label}.md'
    path.write_text(
        f'# {label}\n\nA note written by the tool-path suite for the {label} case.\n\nIt has two paragraphs.\n',
        encoding='utf-8',
    )
    (result,) = side_.upload([(path, name)])
    assert result.get('action') == 'complete', result
    return name, object_id(name)


@needs_tools
def test_remove_document_removes_exactly_that_documents_rows(side, deployment, tmp_path):
    name, oid = _own_document(side, 'remove', tmp_path)
    before = deployment.service.counts(side.collection)
    out = side.ok('remove_document', {'object_ids': [oid, 'no-such-document']})
    assert out['removed'] == [{'objectId': oid, 'chunks_removed': before[oid]}]
    assert out['removed_chunks'] == before[oid] and out['not_found'] == ['no-such-document']
    audit = out['audit']
    assert audit['action'] == 'vector.remove_document' and audit['node'] == 'store_1'
    assert audit['object_ids'] == [oid, 'no-such-document'] and audit['rows'] == before[oid]
    assert audit['caller']['auth'] in ('account', 'task')
    assert not {'content', 'page_content', 'embedding', 'values', 'vector', 'snip'} & _keys(audit)
    after = deployment.service.counts(side.collection)
    assert oid not in after and {k: v for k, v in before.items() if k != oid} == after


def _write_cases() -> List[Tuple[str, str, str, str, Callable[[str], Dict[str, Any]], str]]:
    """(label, source, node, tool, input for an objectId, expected code)."""

    def upsert(oid: str, **extra) -> Dict[str, Any]:
        return {'documents': [{'object_id': oid, 'content': 'A note the gate must refuse.', **extra}]}

    forged = {'origin': 'agent', 'source_type': 'tools', 'targeted': True, 'caller': {'auth': 'agent'}}
    return [
        ('chat token', 'chat_1', 'store_1', 'remove_document', lambda oid: {'object_ids': [oid]}, 'WRITES_SOURCE'),
        ('ingest token', 'ingest_1', 'store_1', 'remove_document', lambda oid: {'object_ids': [oid]}, 'WRITES_SOURCE'),
        (
            'store_2 (switch off)',
            'tools_1',
            'store_2',
            'remove_document',
            lambda oid: {'object_ids': [oid]},
            'WRITES_DISABLED',
        ),
        (
            'control record',
            'tools_1',
            'store_1',
            'remove_document',
            lambda oid: {'object_ids': ['schema']},
            'RESERVED_ID',
        ),
        (
            'legacy delete of the control record',
            'tools_1',
            'store_1',
            'delete',
            lambda oid: {'object_ids': ['schema']},
            'RESERVED_ID',
        ),
        (
            'legacy delete through chat',
            'chat_1',
            'store_1',
            'delete',
            lambda oid: {'object_ids': [oid]},
            'WRITES_SOURCE',
        ),
        ('upsert of the control record', 'tools_1', 'store_1', 'upsert', lambda oid: upsert('schema'), 'RESERVED_ID'),
        (
            'upsert with a caller-supplied embedding',
            'tools_1',
            'store_1',
            'upsert',
            lambda oid: upsert(oid, embedding=[0.01] * DIMENSION, embedding_model=EMBEDDING_MODEL),
            'INVALID_INPUT',
        ),
        (
            'a forged call context inside input',
            'chat_1',
            'store_1',
            'remove_document',
            lambda oid: {'object_ids': [oid], '__tool_context__': forged},
            'WRITES_SOURCE',
        ),
    ]


@needs_tools
@pytest.mark.parametrize('case', _write_cases(), ids=lambda c: c[0])
def test_writes_are_refused_with_the_data_unchanged(side, deployment, tmp_path, case):
    label, source, node, tool, make_input, expected = case
    _name, oid = _own_document(side, re.sub(r'\W+', '-', label), tmp_path)
    before = deployment.service.counts(side.collection)
    assert side.refused(tool, make_input(oid), source=source, node=node) == expected, label
    assert deployment.service.counts(side.collection) == before
    side.ok('remove_document', {'object_ids': [oid]})


@needs_tools
def test_a_broadcast_write_is_refused(side, deployment, tmp_path):
    _name, oid = _own_document(side, 'broadcast', tmp_path)
    before = deployment.service.counts(side.collection)
    # A broadcast reaches the first node that has the tool; which store that is decides the code.
    first = side.ok('dialect', node='')
    expected = 'WRITES_BROADCAST' if first['allow_writes'] else 'WRITES_DISABLED'
    assert side.refused('remove_document', {'object_ids': [oid]}, node='') == expected
    assert deployment.service.counts(side.collection) == before
    side.ok('remove_document', {'object_ids': [oid]})


@needs_tools
def test_the_write_switch_default_is_the_shared_constant(deployment):
    """store_1 without allow_writes follows VECTOR_ALLOW_WRITES_DEFAULT (vx_defaults.py)."""
    pipe = _pipeline(
        deployment.provider,
        deployment.service,
        deployment.new.collection,
        deployment.stub.url,
        store_1={'allow_writes': None},
    )
    variant = _Side(
        deployment.engine, deployment.provider, 'switch-default', deployment.new.collection, pipe, ('tools_1',)
    )
    try:
        assert variant.ok('dialect')['allow_writes'] is vx_defaults.VECTOR_ALLOW_WRITES_DEFAULT
        oid = next(iter(deployment.new.documents.values()))
        before = deployment.service.counts(deployment.new.collection)
        if vx_defaults.VECTOR_ALLOW_WRITES_DEFAULT:
            pytest.skip(
                'VECTOR_ALLOW_WRITES_DEFAULT is on: the refusal row does not apply (the allowed path is covered above)'
            )
        assert variant.refused('remove_document', {'object_ids': [oid]}) == 'WRITES_DISABLED'
        assert deployment.service.counts(deployment.new.collection) == before
    finally:
        variant.stop()


# ---------------------------------------------------------------------------
# The stock RAG shape (no Tools source) and the pooled rocketride_vector pass
# ---------------------------------------------------------------------------


def _stock_rag_pipeline(service: _PgVector, collection: str, stub_url: str) -> Dict[str, Any]:
    """The shape of examples/rag-pipeline.pipe on pgvector (webhook ingest, chat, no Tools source)."""
    chunker = json.loads(
        (_REPO / 'apps' / 'vector-ui' / 'tests' / 'fixtures' / 'chunking.json').read_text(encoding='utf-8')
    )
    local = {
        **service.overrides(collection),
        'score': 0.3,
        'similarity': 'cosine',
        'serverName': 'postgres',
        'allow_writes': True,
    }

    def src(cid, provider, name):
        return {
            'id': cid,
            'provider': provider,
            'name': name,
            'config': {'hideForm': True, 'mode': 'Source', 'parameters': {}, 'type': provider, 'name': name},
        }

    return {
        'name': f'vx-toolpath stock RAG {collection}',
        'project_id': str(uuid.uuid4()),
        'components': [
            src('webhook_1', 'webhook', 'Webhook'),
            {
                'id': 'parse_1',
                'provider': 'parse',
                'name': 'Parse',
                'config': {},
                'input': [{'lane': 'tags', 'from': 'webhook_1'}],
            },
            {
                'id': 'chunk_1',
                'provider': 'preprocessor_langchain',
                'name': 'Chunker',
                'config': chunker['chunk_1']['config'],
                'input': [{'lane': 'text', 'from': 'parse_1'}],
            },
            {
                'id': 'embed_1',
                'provider': 'embedding_transformer',
                'name': 'Embedding',
                'config': {'profile': 'miniAll', 'parameters': {}},
                'input': [{'lane': 'documents', 'from': 'chunk_1'}],
            },
            {
                'id': 'store_1',
                'provider': 'postgres',
                'name': 'pgvector',
                'config': {'profile': 'local', 'local': dict(local), 'parameters': {}},
                'input': [{'lane': 'documents', 'from': 'embed_1'}],
            },
            src('chat_1', 'chat', 'Chat'),
            {
                'id': 'embed_2',
                'provider': 'embedding_transformer',
                'name': 'Embedding (chat)',
                'config': {'profile': 'miniAll', 'parameters': {}},
                'input': [{'lane': 'questions', 'from': 'chat_1'}],
            },
            {
                'id': 'store_2',
                'provider': 'postgres',
                'name': 'pgvector (chat)',
                'config': {'profile': 'local', 'local': dict(local), 'parameters': {}},
                'input': [{'lane': 'questions', 'from': 'embed_2'}],
            },
            {
                'id': 'llm_1',
                'provider': 'llm_openai_api',
                'name': 'Local stub LLM',
                'config': {
                    'profile': 'custom',
                    'custom': {
                        'model': 'gpt-4o-mini',
                        'base_url': stub_url,
                        'apikey': 'local-stub-not-a-key',
                        'modelTotalTokens': 16384,
                    },
                    'parameters': {},
                },
                'input': [{'lane': 'questions', 'from': 'store_2'}],
            },
            {
                'id': 'response_1',
                'provider': 'response_answers',
                'name': 'Return Answers',
                'config': {'laneName': 'answers'},
                'input': [{'lane': 'answers', 'from': 'llm_1'}],
            },
        ],
    }


@pytest.mark.skip(reason=NEEDS_STOCK_RAG)
def test_a_pipeline_without_a_tools_source_is_read_only(engine, stub, corpus_files):
    service = _PgVector('postgres')
    reason = service.unavailable()
    if reason:
        if _DB_TESTS_REQUIRED:
            pytest.fail(f'RR_REQUIRE_DB_TESTS is set but {reason}', pytrace=False)
        pytest.skip(reason)
    collection = f'vx_tp_{RUN}_stock'
    pipe = _stock_rag_pipeline(service, collection, stub.url)
    side_ = _Side(engine, 'stock_rag', 'stock', collection, pipe, ('chat_1', 'webhook_1'))
    try:
        path, name = corpus_files[0]
        (result,) = engine.run(engine.client.send_files([(str(path), {'name': name})], side_.tokens['webhook_1']))
        assert result.get('action') == 'complete', result
        oid = object_id(name)
        assert side_.ok('dialect', source='chat_1', node='store_2')['provider'] == 'postgres'
        assert side_.ok('stats', source='chat_1', node='store_2')['documents'] == 1
        before = service.counts(collection)
        assert (
            side_.refused('remove_document', {'object_ids': [oid]}, source='chat_1', node='store_2') == 'WRITES_SOURCE'
        )
        assert service.counts(collection) == before
        # The ingest-side store is not on the chat source's path at all.
        with pytest.raises(CommandException, match='not found in pipeline'):
            side_.tool('stats', source='chat_1', node='store_1')
    finally:
        side_.stop()
        service.drop(collection)


@pytest.mark.skip(reason=NEEDS_POOLER)
def test_rocketride_vector_through_the_transaction_pooler(engine, broker, stub, deployment):
    if deployment.provider != 'rocketride_vector':
        pytest.skip('NOT RUN: the pooled pass is for rocketride_vector.pipe only')
    service: _PgVector = deployment.service
    if not service.pooler_dsn:
        pytest.skip(
            'NOT RUN: RR_TEST_PGVECTOR_POOLER_DSN is not set (the transaction-mode pooler in front of pgvector)'
        )
    direct = broker.dsn
    broker.dsn = service.broker_dsn(service.pooler_dsn)
    pipe = _pipeline('rocketride_vector', service, deployment.new.collection, stub.url)
    pooled = _Side(engine, 'rocketride_vector', 'pooled', deployment.new.collection, pipe, ('tools_1',))
    try:
        oid = deployment.new.multi
        chunks = len(service.chunk_ids(deployment.new.collection, oid))
        (item,) = pooled.ok('vectors', {'keys': [[oid, 0]]})['items']
        k = min(3, chunks)
        found = pooled.ok('search', {'vector': item['values'], 'top_k': k, 'filter': {'objectIds': [oid]}})
        assert len(found['results']) == k, 'a filtered search through the pooler returned fewer than k rows'
        assert all(r['metadata']['objectId'] == oid for r in found['results'])
        assert pooled.ok('dialect')['health']['collection_exists'] is True
    finally:
        pooled.stop()
        broker.dsn = direct


# ---------------------------------------------------------------------------
# Last: nothing secret in any answer of the run
# ---------------------------------------------------------------------------


def _non_content(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _non_content(v) for k, v in value.items() if k not in CONTENT_KEYS}
    if isinstance(value, list):
        return [_non_content(v) for v in value]
    return value


def test_no_answer_carries_a_host_credential_or_token(deployment, broker, engine):
    answers = [a for a in ANSWERS if a[0] == deployment.provider]
    assert answers, 'no tool answers were recorded for this template'
    banned = deployment.service.secrets() + [broker.token, engine.apikey, broker.url]
    for template, kind, tool, answer in answers:
        blob = json.dumps(_non_content(answer), default=str)
        leaked = [s for s in banned if s and s in blob]
        assert leaked == [], f'{template}/{kind} {tool} answer carries {leaked}'
