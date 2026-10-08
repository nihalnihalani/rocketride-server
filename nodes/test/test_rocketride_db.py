# =============================================================================
# RocketRide Engine
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

"""Unit tests for the RocketRide cloud DB nodes (no database required).

Covers the shared connection seam (``ai.common.rocketride_db``), the OSS
``Account.resolve_db_dsn`` stub, the ``rocketride_sql`` connection override,
and the ``rocketride_vector`` HNSW default-index logic. Real base classes are
loaded from disk with ``rocketlib`` and heavy drivers stubbed, mirroring
``test_graph_neo4j.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
import types

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AI_SRC = _REPO / 'packages' / 'ai' / 'src'
_RRDB_PATH = _AI_SRC / 'ai' / 'common' / 'rocketride_db.py'
_ACCOUNT_BASE = _AI_SRC / 'ai' / 'account' / 'base.py'
_ACCOUNT_OSS = _AI_SRC / 'ai' / 'account' / 'oss' / '__init__.py'
_SQL_NODE_DIR = _REPO / 'nodes' / 'src' / 'nodes' / 'rocketride_sql'
_VEC_NODE_DIR = _REPO / 'nodes' / 'src' / 'nodes' / 'rocketride_vector'

TEST_DSN = 'postgresql://rruser:rrpass@localhost:55432/rrtenant'


def _load_from_path(name: str, path: Path, *, is_package: bool = False):
    search = [str(path.parent)] if is_package else None
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=search)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_rrdb():
    """Load ai.common.rocketride_db in isolation (it only imports stdlib)."""
    return _load_from_path('_test_rocketride_db_helpers', _RRDB_PATH)


rrdb = _load_rrdb()


# ---------------------------------------------------------------------------
# Shared seam helpers
# ---------------------------------------------------------------------------


class TestDsnHelpers:
    def test_url_gets_psycopg2_driver(self):
        assert rrdb.to_sqlalchemy_url(TEST_DSN) == 'postgresql+psycopg2://rruser:rrpass@localhost:55432/rrtenant'

    def test_postgres_scheme_gets_psycopg2_driver(self):
        assert rrdb.to_sqlalchemy_url('postgres://u:p@h/db') == 'postgresql+psycopg2://u:p@h/db'

    def test_explicit_driver_passes_through(self):
        dsn = 'postgresql+psycopg2://u:p@h/db'
        assert rrdb.to_sqlalchemy_url(dsn) == dsn

    def test_keyvalue_dsn_passes_through(self):
        dsn = 'host=localhost dbname=rrtenant user=rruser'
        assert rrdb.to_sqlalchemy_url(dsn) == dsn

    def test_parse_dsn_fields(self):
        fields = rrdb.parse_dsn_fields(TEST_DSN)
        assert fields == {
            'host': 'localhost',
            'port': 55432,
            'user': 'rruser',
            'password': 'rrpass',
            'database': 'rrtenant',
        }

    def test_parse_dsn_fields_unquotes_credentials(self):
        fields = rrdb.parse_dsn_fields('postgresql://u%40x:p%23w@h:5432/db')
        assert fields['user'] == 'u@x'
        assert fields['password'] == 'p#w'

    def test_parse_keyvalue_dsn_yields_empty_fields(self):
        fields = rrdb.parse_dsn_fields('host=x dbname=y')
        assert fields['host'] == ''
        assert fields['database'] == ''

    def test_parse_malformed_port_degrades_that_field_only(self):
        fields = rrdb.parse_dsn_fields('postgresql://u:p@h:notaport/db')
        assert fields['port'] is None
        assert fields['host'] == 'h'
        assert fields['database'] == 'db'

    def test_parse_malformed_authority_yields_empty_fields(self):
        # Mismatched IPv6 bracket — urlparse itself raises ValueError.
        fields = rrdb.parse_dsn_fields('postgresql://[::1/db')
        assert fields == {'host': '', 'port': None, 'user': '', 'password': '', 'database': ''}


class TestClientId:
    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv(rrdb.CLIENT_ID_ENV, raising=False)
        with pytest.raises(ValueError, match='signed-in RocketRide cloud identity'):
            rrdb.current_client_id()

    def test_present_env_returned_stripped(self, monkeypatch):
        monkeypatch.setenv(rrdb.CLIENT_ID_ENV, '  tenant-42  ')
        assert rrdb.current_client_id() == 'tenant-42'


class TestResolveRocketrideDsn:
    """The full seam: injected env DSN first, else account singleton via async bridge."""

    def _install_fake_account(self, monkeypatch, resolver):
        monkeypatch.delenv(rrdb.DB_DSN_ENV, raising=False)
        ai_pkg = types.ModuleType('ai')
        ai_pkg.__path__ = []
        account_mod = types.ModuleType('ai.account')
        account_mod.account = types.SimpleNamespace(resolve_db_dsn=resolver)
        monkeypatch.setitem(sys.modules, 'ai', ai_pkg)
        monkeypatch.setitem(sys.modules, 'ai.account', account_mod)

    def test_injected_env_dsn_wins(self, monkeypatch):
        """The task-engine-injected ROCKETRIDE_DB_DSN short-circuits everything."""

        async def fake(client_id):  # pragma: no cover — must not be reached
            raise AssertionError('account must not be consulted when the env DSN is present')

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.setenv(rrdb.DB_DSN_ENV, f'  {TEST_DSN}  ')
        # No client id needed on the injected path either.
        monkeypatch.delenv(rrdb.CLIENT_ID_ENV, raising=False)
        assert rrdb.resolve_rocketride_dsn() == TEST_DSN

    def test_resolve_error_env_surfaces_broker_failure(self, monkeypatch):
        """A server-side resolution failure names the real cause, not sign-in."""

        async def fake(client_id):  # pragma: no cover — must not be reached
            raise AssertionError('account must not be consulted when a resolve error is present')

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.delenv(rrdb.DB_DSN_ENV, raising=False)
        monkeypatch.setenv(rrdb.DB_RESOLVE_ERROR_ENV, 'DB broker request failed: HTTP 503')
        with pytest.raises(ValueError, match='HTTP 503'):
            rrdb.resolve_rocketride_dsn()

    def test_empty_env_dsn_falls_back_to_account(self, monkeypatch):
        async def fake(client_id):
            return TEST_DSN

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.setenv(rrdb.DB_DSN_ENV, '   ')
        monkeypatch.setenv(rrdb.CLIENT_ID_ENV, 'tenant-42')
        assert rrdb.resolve_rocketride_dsn() == TEST_DSN

    def test_resolves_via_fake_account(self, monkeypatch):
        seen = {}

        async def fake(client_id):
            seen['client_id'] = client_id
            return TEST_DSN

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.setenv(rrdb.CLIENT_ID_ENV, 'tenant-42')
        assert rrdb.resolve_rocketride_dsn() == TEST_DSN
        assert seen['client_id'] == 'tenant-42'

    def test_empty_dsn_raises(self, monkeypatch):
        async def fake(client_id):
            return ''

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.setenv(rrdb.CLIENT_ID_ENV, 'tenant-42')
        with pytest.raises(ValueError, match='empty DSN'):
            rrdb.resolve_rocketride_dsn()

    def test_rejects_running_event_loop_before_creating_coroutine(self, monkeypatch):
        """Reject running-loop callers before creating the resolver coroutine."""
        created = []

        def fake(client_id):
            async def resolve():
                return TEST_DSN

            coro = resolve()
            created.append(coro)
            return coro

        self._install_fake_account(monkeypatch, fake)
        monkeypatch.setenv(rrdb.CLIENT_ID_ENV, 'tenant-42')

        async def call_from_loop():
            return rrdb.resolve_rocketride_dsn()

        try:
            with pytest.raises(RuntimeError, match='running event loop'):
                asyncio.run(call_from_loop())
            assert created == []
        finally:
            # Close any coroutine created if the regression returns.
            for coro in created:
                coro.close()


# ---------------------------------------------------------------------------
# Account layer: OSS stub + base default
# ---------------------------------------------------------------------------


class TestAccountStub:
    @pytest.fixture()
    def account_cls(self, monkeypatch):
        """Load the OSS Account with ``depends`` stubbed out."""
        depends_mod = types.ModuleType('depends')
        depends_mod.depends = lambda *a, **kw: None
        monkeypatch.setitem(sys.modules, 'depends', depends_mod)

        ai_pkg = types.ModuleType('ai')
        ai_pkg.__path__ = [str(_AI_SRC / 'ai')]
        monkeypatch.setitem(sys.modules, 'ai', ai_pkg)
        account_pkg = types.ModuleType('ai.account')
        account_pkg.__path__ = [str(_ACCOUNT_BASE.parent)]
        monkeypatch.setitem(sys.modules, 'ai.account', account_pkg)
        base_mod = _load_from_path('ai.account.base', _ACCOUNT_BASE)
        monkeypatch.setitem(sys.modules, 'ai.account.base', base_mod)
        oss_mod = _load_from_path('ai.account.oss', _ACCOUNT_OSS, is_package=True)
        monkeypatch.setitem(sys.modules, 'ai.account.oss', oss_mod)
        return base_mod.AccountBase, oss_mod.Account

    def test_oss_stub_raises_cloud_signin_message(self, account_cls):
        _, account = account_cls
        with pytest.raises(NotImplementedError, match='require signing into RocketRide cloud'):
            asyncio.run(account().resolve_db_dsn('tenant-42'))

    def test_base_default_raises(self, account_cls):
        base, _ = account_cls

        class Minimal(base):
            async def authenticate(self, credential):
                return None

        with pytest.raises(NotImplementedError):
            asyncio.run(Minimal().resolve_db_dsn('tenant-42'))


# ---------------------------------------------------------------------------
# rocketride_sql: connection resolution override
# ---------------------------------------------------------------------------


def _sql_iglobal_cls(monkeypatch):
    """Load rocketride_sql/IGlobal with the database base loaded from disk."""
    pytest.importorskip('sqlalchemy')

    rocketlib = types.ModuleType('rocketlib')
    rocketlib.IGlobalBase = type('IGlobalBase', (), {})
    rocketlib.error = lambda *a, **kw: None
    rocketlib.warning = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, 'rocketlib', rocketlib)

    ai_pkg = types.ModuleType('ai')
    ai_pkg.__path__ = []
    common_pkg = types.ModuleType('ai.common')
    common_pkg.__path__ = []
    config = types.ModuleType('ai.common.config')
    config.Config = types.SimpleNamespace(getNodeConfig=lambda *a, **kw: {})
    monkeypatch.setitem(sys.modules, 'ai', ai_pkg)
    monkeypatch.setitem(sys.modules, 'ai.common', common_pkg)
    monkeypatch.setitem(sys.modules, 'ai.common.config', config)

    rrdb_mod = _load_from_path('ai.common.rocketride_db', _RRDB_PATH)
    monkeypatch.setitem(sys.modules, 'ai.common.rocketride_db', rrdb_mod)

    db_global = _load_from_path(
        'ai.common.database.db_global_base',
        _AI_SRC / 'ai' / 'common' / 'database' / 'db_global_base.py',
    )
    database_pkg = types.ModuleType('ai.common.database')
    database_pkg.__path__ = []
    database_pkg.DatabaseGlobalBase = db_global.DatabaseGlobalBase
    monkeypatch.setitem(sys.modules, 'ai.common.database', database_pkg)
    monkeypatch.setitem(sys.modules, 'ai.common.database.db_global_base', db_global)

    iglobal = _load_from_path('nodes.rocketride_sql.IGlobal', _SQL_NODE_DIR / 'IGlobal.py')
    return iglobal.IGlobal, rrdb_mod


class TestRocketrideSqlConnection:
    def _with_fake_account(self, monkeypatch):
        account_mod = types.ModuleType('ai.account')

        async def fake(client_id):
            return TEST_DSN

        account_mod.account = types.SimpleNamespace(resolve_db_dsn=fake)
        monkeypatch.setitem(sys.modules, 'ai.account', account_mod)
        monkeypatch.setenv('ROCKETRIDE_CLIENT_ID', 'tenant-42')
        monkeypatch.delenv('ROCKETRIDE_DB_DSN', raising=False)

    def test_connection_params_come_from_resolved_dsn(self, monkeypatch):
        cls, _ = _sql_iglobal_cls(monkeypatch)
        self._with_fake_account(monkeypatch)
        glb = cls()
        params = glb._connection_params({'table': ' widgets '})
        assert params['host'] == 'localhost'
        assert params['user'] == 'rruser'
        assert params['password'] == 'rrpass'
        assert params['database'] == 'rrtenant'
        assert params['table'] == 'widgets'

    def test_build_connection_url_uses_cached_dsn(self, monkeypatch):
        cls, _ = _sql_iglobal_cls(monkeypatch)
        self._with_fake_account(monkeypatch)
        glb = cls()
        params = glb._connection_params({})
        url = glb._build_connection_url(params)
        assert url == 'postgresql+psycopg2://rruser:rrpass@localhost:55432/rrtenant'

    def test_no_connection_fields_read_from_config(self, monkeypatch):
        """host/user/password in config must be ignored — the DSN wins."""
        cls, _ = _sql_iglobal_cls(monkeypatch)
        self._with_fake_account(monkeypatch)
        glb = cls()
        params = glb._connection_params({'host': 'evil', 'user': 'evil', 'password': 'evil'})
        assert params['host'] == 'localhost'
        assert params['user'] == 'rruser'
        url = glb._build_connection_url(params)
        assert 'evil' not in url


# ---------------------------------------------------------------------------
# rocketride_vector: the shared pgvector driver over the psycopg2 test double
#
# The real node Store and the real ai.common.store.pgvector driver run against
# nodes/test/mocks/psycopg2 (an in-memory database that understands the
# driver's statements). Every behaviour checked here is also checked live in
# test_rocketride_db_full.py / test_store_postgres_full.py.
# ---------------------------------------------------------------------------

_MOCK_PSYCOPG2 = _REPO / 'nodes' / 'test' / 'mocks' / 'psycopg2'
_SWAPPED_MODULES = (
    'psycopg2',
    'psycopg2.sql',
    'psycopg2.extensions',
    'depends',
    'ai.common.store.pgvector',
    'ai.common.store.pgvector.sql',
    'ai.common.store.pgvector.pool',
    'ai.common.store.pgvector.driver',
    'nodes.rocketride_vector',
    'nodes.rocketride_vector.IEndpoint',
    'nodes.rocketride_vector.IGlobal',
    'nodes.rocketride_vector.IInstance',
    'nodes.rocketride_vector.rocketride_vector',
)


@pytest.fixture()
def mock_rv(monkeypatch):
    """The real rocketride_vector Store, with psycopg2 replaced by the test double; sys.modules restored afterwards."""
    import importlib

    saved = {name: sys.modules.get(name) for name in _SWAPPED_MODULES}
    import ai.common.store as store_pkg

    saved_attr = store_pkg.__dict__.get('pgvector')
    for name in _SWAPPED_MODULES:
        sys.modules.pop(name, None)
    try:
        import depends as real_depends  # noqa: F401 - reloaded below as a stand-in

        depends_mod = types.ModuleType('depends')
        depends_mod.__dict__.update(saved['depends'].__dict__ if saved['depends'] else {})
        depends_mod.depends = lambda *a, **kw: None
        sys.modules['depends'] = depends_mod
        spec = importlib.util.spec_from_file_location(
            'psycopg2', _MOCK_PSYCOPG2 / '__init__.py', submodule_search_locations=[str(_MOCK_PSYCOPG2)]
        )
        psycopg2_mock = importlib.util.module_from_spec(spec)
        sys.modules['psycopg2'] = psycopg2_mock
        spec.loader.exec_module(psycopg2_mock)
        psycopg2_mock.MockConnection.reset()

        from ai.common.config import Config

        monkeypatch.setattr(Config, 'getNodeConfig', staticmethod(lambda provider, connConfig: dict(connConfig)))
        monkeypatch.setenv('ROCKETRIDE_DB_DSN', TEST_DSN)
        monkeypatch.delenv('ROCKETRIDE_DB_RESOLVE_ERROR', raising=False)
        store_mod = importlib.import_module('nodes.rocketride_vector.rocketride_vector')
        driver = importlib.import_module('ai.common.store.pgvector.driver')
        warnings: list[str] = []
        monkeypatch.setattr(driver, 'warning', warnings.append)
        yield types.SimpleNamespace(
            Store=store_mod.Store, db=psycopg2_mock.MockConnection, psycopg2=psycopg2_mock, warnings=warnings
        )
    finally:
        for name in _SWAPPED_MODULES:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]
        if saved_attr is not None:
            store_pkg.pgvector = saved_attr
        else:
            store_pkg.__dict__.pop('pgvector', None)


def _make_store(env, config):
    return env.Store('rocketride_vector', config, {})


def _statements(env, tag=None):
    """Every statement the driver sent, optionally only those named ``tag``."""
    out = []
    for conn in env.db.opened:
        for text, _params in conn.executed:
            if tag is None or text.startswith(f'/* rr-pgvector:{tag} */'):
                out.append(text)
    return out


def _doc(object_id, chunk_id, embedding, content=None):
    from ai.common.schema import Doc, DocMetadata

    return Doc(
        page_content=content if content is not None else f'{object_id}/{chunk_id}',
        metadata=DocMetadata(objectId=object_id, chunkId=chunk_id, isDeleted=False, signature='sig', size=7),
        embedding=list(embedding),
        embedding_model='m',
    )


class TestRocketrideVectorStore:
    def test_connects_via_resolved_dsn(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        # No client_id on the store: identity rides the task file (#1686);
        # tenant scoping keys on the DSN's database (see IGlobal's subKey).
        assert store.host == 'localhost'
        assert store.port == 55432
        assert store.database == 'rrtenant'
        conn = mock_rv.db.opened[0]
        assert conn.dsn == TEST_DSN and conn.application_name == 'rocketride-pgvector'

    def test_invalid_collection_rejected(self, mock_rv):
        with pytest.raises(ValueError, match='Invalid collection name'):
            _make_store(mock_rv, {'collection': 'bad-name;drop', 'similarity': 'cosine'})

    @pytest.mark.parametrize(
        ('similarity', 'opclass'),
        [
            ('cosine', 'vector_cosine_ops'),
            ('l2', 'vector_l2_ops'),
            ('inner_product', 'vector_ip_ops'),
        ],
    )
    def test_hnsw_index_opclass_follows_similarity(self, mock_rv, similarity, opclass):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': similarity})
        store._createCollection(vectorSize=5)
        assert any(
            sql.startswith('/* rr-pgvector:create_table */ CREATE TABLE IF NOT EXISTS "rr_vec"')
            for sql in _statements(mock_rv)
        )
        index_sql = _statements(mock_rv, 'create_hnsw_index')
        assert len(index_sql) == 1
        assert f'USING hnsw ("embedding" {opclass})' in index_sql[0]
        assert '"rr_vec_embedding_hnsw"' in index_sql[0]
        assert 'm = 16' in index_sql[0]
        assert 'ef_construction = 64' in index_sql[0]

    def test_hnsw_params_overridable(self, mock_rv):
        store = _make_store(
            mock_rv,
            {'collection': 'rr_vec', 'similarity': 'cosine', 'hnsw_m': 32, 'hnsw_ef_construction': 128},
        )
        store._createCollection(vectorSize=5)
        index_sql = _statements(mock_rv, 'create_hnsw_index')
        assert 'm = 32' in index_sql[0]
        assert 'ef_construction = 128' in index_sql[0]

    def test_render_orders_chunks_and_bridges_gaps(self, mock_rv):
        """Chunks at 0, 1 and 3 (gap at 2): index order preserved, gap skipped."""
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('obj-1', 0, [1, 0, 0, 0, 0], 'A')])
        store.addChunks([_doc('obj-1', 3, [1, 0, 0, 0, 0], 'D'), _doc('obj-1', 1, [1, 0, 0, 0, 0], 'B')])
        out: list[str] = []
        store.render('obj-1', out.append)
        assert ''.join(out) == 'ABD'

    def test_render_empty_batch_emits_nothing(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('obj-2', 0, [1, 0, 0, 0, 0], 'A')])
        out: list[str] = []
        store.render('obj-1', out.append)
        assert out == []

    def test_render_single_high_chunk_id(self, mock_rv):
        """One row with a high chunkId renders that row — allocation is bounded
        by rows fetched, never by the chunkId value.
        """
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('obj-0', 0, [1, 0, 0, 0, 0], 'seed')])
        store.addChunks([_doc('obj-1', 999_999, [1, 0, 0, 0, 0], 'X')])
        out: list[str] = []
        store.render('obj-1', out.append)
        assert out == ['X']

    def test_hnsw_params_clamped_to_pgvector_bounds(self, mock_rv):
        store = _make_store(
            mock_rv,
            {'collection': 'rr_vec', 'similarity': 'cosine', 'hnsw_m': 1, 'hnsw_ef_construction': 1},
        )
        # pgvector requires m >= 2, ef_construction >= 4 and >= 2 * m.
        assert store.hnsw_m == 2
        assert store.hnsw_ef_construction == 4

    def test_hnsw_ef_construction_raised_to_twice_m(self, mock_rv):
        store = _make_store(
            mock_rv,
            {'collection': 'rr_vec', 'similarity': 'cosine', 'hnsw_m': 64, 'hnsw_ef_construction': 64},
        )
        assert store.hnsw_ef_construction == 128

    def test_hnsw_skipped_above_dimension_ceiling(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store._createCollection(vectorSize=2001)
        assert _statements(mock_rv, 'create_table')
        assert not _statements(mock_rv, 'create_hnsw_index')
        assert any('2000' in w and 'Skipping index' in w for w in mock_rv.warnings)

    def test_hnsw_created_at_dimension_ceiling(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store._createCollection(vectorSize=2000)
        assert _statements(mock_rv, 'create_hnsw_index')
        assert not mock_rv.warnings


class TestPgVectorTransactions:
    """Transaction hygiene of the shared driver (live twins: test_store_postgres_full.py TestConnections)."""

    def test_reads_are_read_only_bounded_and_end_their_transaction(self, mock_rv):
        from ai.common.schema import DocFilter, QuestionText

        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('a', 0, [1, 0, 0, 0, 0])])
        query = QuestionText(text='q')
        query.embedding = [1, 0, 0, 0, 0]
        assert [d.metadata.objectId for d in store.searchSemantic(query, DocFilter(limit=3))] == ['a']
        begins = _statements(mock_rv, 'begin_read')
        assert len(begins) > 1
        assert all('SET TRANSACTION READ ONLY' in b and "statement_timeout = '30000ms'" in b for b in begins)
        # The open probe reads the pgvector version; every read after it sets the iterative scan.
        assert 'hnsw.iterative_scan' not in begins[0]
        assert all('hnsw.iterative_scan = relaxed_order' in b for b in begins[1:])
        assert all(b.startswith("/* rr-pgvector:begin_read */ SELECT '[0]'::vector;") for b in begins)
        # Nothing is ever set for the session (a transaction-mode pooler would leak it).
        every = _statements(mock_rv)
        assert not [s for s in every if re.search(r'(^|; )SET (?!LOCAL|TRANSACTION)', s.split('*/', 1)[-1].strip())]
        assert all(conn.get_transaction_status() == 0 for conn in mock_rv.db.opened)

    def test_iterative_scan_left_out_before_pgvector_0_8(self, mock_rv):
        mock_rv.db.extension_version = '0.7.4'
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.countChunks(None)
        assert not any('hnsw.iterative_scan' in b for b in _statements(mock_rv, 'begin_read'))

    def test_failed_statement_does_not_poison_the_next_call(self, mock_rv):
        from ai.common.schema import DocFilter

        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('a', 0, [1, 0, 0, 0, 0])])
        mock_rv.db.fail_next['count_chunks'] = mock_rv.psycopg2.ProgrammingError('boom', '42000')
        with pytest.raises(Exception, match='boom'):
            store.countChunks(DocFilter())
        assert store.countChunks(DocFilter()) == 1
        assert all(conn.get_transaction_status() == 0 for conn in mock_rv.db.opened)

    def test_failed_write_rolls_back_the_whole_batch(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('a', 0, [1, 0, 0, 0, 0]), _doc('a', 1, [1, 0, 0, 0, 0])])
        mock_rv.db.fail_next['insert'] = mock_rv.psycopg2.OperationalError('insert failed', '53100')
        with pytest.raises(Exception):
            store.addChunks([_doc('a', 0, [0, 1, 0, 0, 0], 'new')])
        rows = sorted((r['objectid'], r['chunkid']) for r in mock_rv.db.table('rr_vec').rows.values())
        assert rows == [('a', 0), ('a', 1), ('schema', 0)]  # the delete of the failed batch was undone

    def test_connection_slots_are_handed_out_first_come_first_served(self, mock_rv):
        """A released slot goes to the longest waiter, never back to a caller that arrives later."""
        import threading
        import time

        from ai.common.store.pgvector.pool import FairGate

        gate = FairGate(1)
        assert gate.acquire(1.0)
        order: list[str] = []

        def waiter(name):
            assert gate.acquire(5.0)
            order.append(name)
            time.sleep(0.05)
            gate.release()

        first = threading.Thread(target=waiter, args=('first',))
        first.start()
        time.sleep(0.1)
        second = threading.Thread(target=waiter, args=('second',))
        second.start()
        time.sleep(0.1)
        gate.release()
        # A caller arriving right after the release must queue behind both waiters.
        assert gate.acquire(5.0)
        order.append('late')
        gate.release()
        first.join(5)
        second.join(5)
        assert order == ['first', 'second', 'late']
        assert gate.acquire(0.01)
        assert not gate.acquire(0.05)  # the only slot is taken: a bounded wait gives up

    def test_unreachable_server_error_names_no_host(self, mock_rv):
        from ai.common.store.errors import StoreError

        mock_rv.db.fail_next['connect'] = mock_rv.psycopg2.OperationalError(
            'connection to server at "10.1.2.3", port 6432 failed: password authentication failed for user "rruser"'
        )
        with pytest.raises(StoreError) as err:
            _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        assert '10.1.2.3' not in str(err.value) and 'rruser' not in str(err.value)

    def test_meta_column_falls_back_while_the_table_is_locked(self, mock_rv):
        store = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        store.addChunks([_doc('a', 0, [1, 0, 0, 0, 0])])
        table = mock_rv.db.table('rr_vec')
        table.columns = [c for c in table.columns if c[0] != 'meta']  # a table without the column
        for row in table.rows.values():
            row.pop('meta', None)
        mock_rv.db.locked_tables.add('rr_vec')
        reopened = _make_store(mock_rv, {'collection': 'rr_vec', 'similarity': 'cosine'})
        reopened.addChunks([_doc('b', 0, [1, 0, 0, 0, 0])])
        info = reopened.describe()
        assert info.meta_column is False and 'extras_not_stored' in info.caveats
        mock_rv.db.locked_tables.clear()
        reopened.META_RETRY_S = 0.0
        reopened.addChunks([_doc('c', 0, [1, 0, 0, 0, 0])])
        assert reopened.describe().meta_column is True
        assert 'meta' in [name for name, _type in mock_rv.db.table('rr_vec').columns]
        rows = {r['objectid']: r for r in mock_rv.db.table('rr_vec').rows.values()}
        assert rows['c']['meta'] == {'size': 7} and 'meta' not in rows['b']


# ---------------------------------------------------------------------------
# Tenancy wording (AGE-T6)
# ---------------------------------------------------------------------------

_GRAPH_NODE_DIR = _REPO / 'nodes' / 'src' / 'nodes' / 'rocketride_graph'
_CLOUD_DB_NODE_DIRS = (_SQL_NODE_DIR, _VEC_NODE_DIR, _GRAPH_NODE_DIR)

# How the docs used to describe the tenant: the signed-in user. The server
# resolves the database by the task's organization (its user only where there
# is no organization), so these phrases describe the wrong tenancy model.
_STALE_TENANT_PHRASES = (
    'signed-in rocketride identity',
    'signed-in rocketride tenant',
    'authenticated client_id',
)


def _prose(path: Path) -> str:
    """A file's text with comment markers, backquotes and line breaks folded away, lower-cased.

    A services.json description is an array of strings shown joined, so the
    seams between its strings are folded away too.
    """
    text = path.read_text(encoding='utf-8')
    text = text.replace('``', '').replace('`', '').replace('", "', '')
    lines = [line.strip().lstrip('#').lstrip('/').strip() for line in text.splitlines()]
    return ' '.join(' '.join(lines).split()).lower()


class TestTenancyWording:
    """The cloud DB nodes describe the database as the organization's (AGE-T6)."""

    @pytest.mark.parametrize('node_dir', _CLOUD_DB_NODE_DIRS, ids=lambda p: p.name)
    def test_no_text_describes_the_signed_in_user_as_the_tenant(self, node_dir):
        stale = [
            f'{path.name}: {phrase!r}'
            for path in sorted(node_dir.iterdir())
            if path.suffix in ('.py', '.json', '.md')
            for phrase in _STALE_TENANT_PHRASES
            if phrase in _prose(path)
        ]
        assert stale == []

    @pytest.mark.parametrize('node_dir', _CLOUD_DB_NODE_DIRS, ids=lambda p: p.name)
    def test_description_and_readme_name_the_organization(self, node_dir):
        assert "the connection to your organization's database" in _prose(node_dir / 'services.json')
        assert 'per organization' in _prose(node_dir / 'README.md')
