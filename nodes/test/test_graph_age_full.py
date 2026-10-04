# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Live connection/transaction lifecycle tests for rocketride_graph (PG16 + AGE 1.5.0).

Concurrency, prepared-statement cleanup, session hygiene, reconnect and
shutdown, against the same disposable database and fixtures as
``test_rocketride_graph_full.py`` (whose ``rr_env`` / ``age_graph`` fixtures
are reused). Synchronisation uses barriers plus server-side ``pg_sleep`` so
the overlapping windows are real, not scheduler luck.

Skips cleanly when the database is unreachable unless ``RR_REQUIRE_DB_TESTS``
is set, in which case the import of the shared module fails the run.

Behind a transaction-mode pooler set ``RR_TEST_AGE_DSN`` to the pooler and
``RR_TEST_AGE_ADMIN_DSN`` to the database itself. Server sessions then belong
to the pooler, so the tests that terminate or count server backends check the
node's own client connections instead.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from .test_rocketride_graph_full import ADMIN_DSN, TEST_DSN, _begin, _db_reachable, age_graph, psycopg2, rr_env

# The shared fixtures are requested by name in the tests below; binding them
# here is what registers them with pytest for this module.
_SHARED_FIXTURES = (rr_env, age_graph)

# A pooler sits between the node and the database when the two DSNs differ.
BEHIND_POOLER = ADMIN_DSN != TEST_DSN

pytestmark = pytest.mark.skipif(not _db_reachable(), reason=f'RocketRide AGE test database not reachable at {TEST_DSN}')


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _age():
    return sys.modules['ai.common.graph.age']


def _plan(statements, *, read_only, columns=('v',)):
    """A hand-built plan whose LAST statement produces the result rows."""
    plan = _age().TranslatedQuery(columns=list(columns), has_return=True)
    for stmt in statements:
        plan.statements.append(stmt)
        plan.binds.append(())
    plan.result_index = len(statements) - 1
    plan.read_only = read_only
    return plan


def _set_pool_size(rr_env, monkeypatch, size):
    monkeypatch.setattr(sys.modules[rr_env.iglobal_cls.__module__], 'DEFAULT_POOL_SIZE', size)


def _on_pooled_session(glb, statement):
    """Run SQL on one of the node's own (idle) sessions, outside any plan."""
    pool = getattr(glb, 'pool', None)
    if pool is None:  # pre-pool code: the one shared connection
        with glb.client.cursor() as cur:
            cur.execute(statement)
            row = cur.fetchone()
        glb.client.rollback()
        return row
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(statement)
            row = cur.fetchone()
        conn.rollback()
        return row


def _admin():
    # Direct to the database (never through a pooler under test): it runs
    # server-side inspection and pg_terminate_backend.
    conn = psycopg2.connect(ADMIN_DSN, connect_timeout=5)
    conn.autocommit = True
    return conn


def _run_threads(targets, timeout=30):
    errors = {}
    results = {}

    def wrap(key, fn):
        try:
            results[key] = fn()
        except BaseException as e:  # noqa: BLE001 - reported to the test
            errors[key] = e

    threads = [threading.Thread(target=wrap, args=(k, fn)) for k, fn in targets.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    assert not any(t.is_alive() for t in threads), 'a worker thread hung'
    return results, errors


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_calls_get_their_own_session_and_settings(self, rr_env, age_graph):
        glb = _begin(rr_env)
        barrier = threading.Barrier(4)

        def call(i):
            def run():
                plan = _plan(
                    [
                        f"SET LOCAL statement_timeout = '{1001 + i}ms'",
                        'SELECT pg_sleep(0.3)',
                        "SELECT pg_backend_pid(), current_setting('transaction_read_only'), "
                        "current_setting('statement_timeout')",
                    ],
                    read_only=(i % 2 == 0),
                    columns=('pid', 'ro', 'timeout'),
                )
                barrier.wait()
                return glb._execute_plan(plan, fetch_cap=1)[0]

            return run

        try:
            results, errors = _run_threads({i: call(i) for i in range(4)})
            assert not errors, errors
            assert len({row[0] for row in results.values()}) == 4, 'concurrent calls shared a session'
            for i, (_pid, read_only, timeout) in results.items():
                assert read_only == ('on' if i % 2 == 0 else 'off')
                assert timeout == f'{1001 + i}ms'
        finally:
            glb.endGlobal()

    def test_failing_call_cannot_reset_a_concurrent_calls_safety_settings(self, rr_env, age_graph):
        glb = _begin(rr_env)
        barrier = threading.Barrier(2)
        failing = _plan(['SELECT pg_sleep(0.15)', 'SELECT 1/0'], read_only=False)
        # Several short statements: on a shared connection the failing call's
        # statements would land between these, inside this transaction.
        reading = _plan(
            [
                "SET LOCAL statement_timeout = '4321ms'",
                *(['SELECT pg_sleep(0.1)'] * 6),
                "SELECT current_setting('transaction_read_only'), current_setting('statement_timeout')",
            ],
            read_only=True,
            columns=('ro', 'timeout'),
        )

        def run_failing():
            barrier.wait()
            return glb._execute_plan(failing, fetch_cap=1)

        def run_reading():
            barrier.wait()
            return glb._execute_plan(reading, fetch_cap=1)[0]

        try:
            results, errors = _run_threads({'fail': run_failing, 'read': run_reading})
            assert isinstance(errors.get('fail'), psycopg2.Error)
            assert 'read' not in errors, errors.get('read')
            assert results['read'] == ('on', '4321ms')
        finally:
            glb.endGlobal()

    def test_read_does_not_see_a_concurrent_uncommitted_write(self, rr_env, age_graph):
        glb = _begin(rr_env, {'allow_execute': True})
        age = _age()
        write = glb._translate("CREATE (:Person {name: 'iso-writer'})", mode=age.TranslateMode.RAW)
        write.statements.append('SELECT pg_sleep(0.8)')
        write.binds.append(())
        write.result_index = len(write.statements) - 1
        started = threading.Event()

        def run_write():
            started.set()
            return glb._execute_plan(write, fetch_cap=1)

        def run_read():
            started.wait(5)
            time.sleep(0.3)  # inside the writer's sleep, before its COMMIT
            return glb._run_query("MATCH (p:Person) WHERE p.name = 'iso-writer' RETURN count(p) AS c")

        try:
            results, errors = _run_threads({'write': run_write, 'read': run_read})
            assert not errors, errors
            assert results['read'] == [{'c': 0}]
            assert glb._run_query("MATCH (p:Person) WHERE p.name = 'iso-writer' RETURN count(p) AS c") == [{'c': 1}]
        finally:
            glb.endGlobal()

    def test_reflection_runs_beside_reads_on_separate_sessions(self, rr_env, age_graph):
        glb = _begin(rr_env)
        barrier = threading.Barrier(3)

        def reflect():
            barrier.wait()
            return glb._reflect_schema()

        def read():
            barrier.wait()
            return glb._run_query('MATCH (p:Person) RETURN count(p) AS c')

        try:
            results, errors = _run_threads({'schema': reflect, 'r1': read, 'r2': read})
            assert not errors, errors
            assert set(results['schema']['nodes']) == {'Person', 'Company'}
            assert results['r1'] == results['r2'] == [{'c': 3}]
        finally:
            glb.endGlobal()

    def test_pool_bounds_open_sessions(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 2)
        glb = _begin(rr_env)
        barrier = threading.Barrier(5)

        def call():
            barrier.wait()
            return glb._execute_plan(_plan(['SELECT pg_sleep(0.3)', 'SELECT pg_backend_pid()'], read_only=True))[0][0]

        try:
            results, errors = _run_threads({i: call for i in range(5)})
            assert not errors, errors
            assert len(set(results.values())) <= 2
            assert glb.pool.size <= 2
        finally:
            glb.endGlobal()


# ---------------------------------------------------------------------------
# prepared statements, quoting, session hygiene
# ---------------------------------------------------------------------------


class TestSessionHygiene:
    def test_failed_parameterised_call_leaves_no_prepared_statement(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 1)
        glb = _begin(rr_env)
        try:
            with pytest.raises(Exception, match='division by zero'):
                glb._run_query('MATCH (p:Person) WHERE p.name = $n RETURN p.age / 0 AS boom', params={'n': 'alice'})
            assert _on_pooled_session(glb, 'SELECT count(*) FROM pg_prepared_statements') == (0,)
            # Two consecutive parameterised calls after the failure still work.
            assert glb._run_query('MATCH (p:Person) WHERE p.name = $n RETURN p.age AS age', params={'n': 'bob'}) == [
                {'age': 25}
            ]
            assert glb._run_query(
                'MATCH (p:Person) WHERE p.age > $a RETURN p.name AS n ORDER BY p.name', params={'a': 26}
            ) == [
                {'n': 'alice'},
                {'n': 'carol'},
            ]
            assert _on_pooled_session(glb, 'SELECT count(*) FROM pg_prepared_statements') == (0,)
        finally:
            glb.endGlobal()

    def test_timeout_mid_execute_also_cleans_up(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 1)
        glb = _begin(rr_env, {'query_timeout_ms': 200})
        try:
            with pytest.raises(Exception, match='statement timeout'):
                glb._run_query(
                    'MATCH (a)-[*1..10]-(b)-[*1..10]-(c) WHERE a.name = $n RETURN count(*) AS c', params={'n': 'alice'}
                )
            assert _on_pooled_session(glb, 'SELECT count(*) FROM pg_prepared_statements') == (0,)
            assert glb._run_query('MATCH (p:Person) WHERE p.name = $n RETURN p.age AS age', params={'n': 'carol'}) == [
                {'age': 41}
            ]
        finally:
            glb.endGlobal()

    def test_query_ending_in_the_quote_tag_runs(self, rr_env, age_graph):
        glb = _begin(rr_env)
        try:
            rows = glb._run_query('MATCH (p:Person) RETURN p.name = $rr_cypher', params={'rr_cypher': 'alice'})
            assert sorted(v for row in rows for v in row.values()) == [False, False, True]
        finally:
            glb.endGlobal()

    def test_no_session_state_survives_a_call(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 1)
        fresh = _admin()
        with fresh.cursor() as cur:
            cur.execute("SELECT current_setting('statement_timeout'), current_setting('search_path')")
            defaults = cur.fetchone()
        fresh.close()
        glb = _begin(rr_env)
        try:
            glb._run_query('MATCH (p:Person) WHERE p.name = $n RETURN p.age AS age', params={'n': 'alice'})
            glb._validate_query('MATCH (p:Person) RETURN p.name')
            state = _on_pooled_session(
                glb,
                "SELECT current_setting('statement_timeout'), current_setting('search_path'), "
                "current_setting('transaction_read_only'), (SELECT count(*) FROM pg_prepared_statements)",
            )
            assert state == (*defaults, 'off', 0)
        finally:
            glb.endGlobal()


# ---------------------------------------------------------------------------
# failure recovery and shutdown
# ---------------------------------------------------------------------------


class TestRecovery:
    def test_idle_connection_dropped_by_server_is_replaced(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 1)
        glb = _begin(rr_env)
        admin = _admin()
        try:
            if BEHIND_POOLER:
                # The pooler owns server sessions; drop the node's own client
                # connection instead (same failure as from the node's side).
                with glb.pool.connection() as conn:
                    victim = conn
                victim.close()
            else:
                (pid,) = _on_pooled_session(glb, 'SELECT pg_backend_pid()')
                with admin.cursor() as cur:
                    cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
                time.sleep(0.2)
            assert glb._run_query('MATCH (p:Person) WHERE p.name = $n RETURN p.age AS age', params={'n': 'alice'}) == [
                {'age': 30}
            ]
            if not BEHIND_POOLER:
                (new_pid,) = _on_pooled_session(glb, 'SELECT pg_backend_pid()')
                assert new_pid != pid
            assert glb.pool.size == 1
        finally:
            admin.close()
            glb.endGlobal()

    def test_connection_lost_during_the_main_statement_is_not_retried(self, rr_env, age_graph, monkeypatch):
        _set_pool_size(rr_env, monkeypatch, 1)
        glb = _begin(rr_env)
        admin = _admin()
        try:
            (pid,) = _on_pooled_session(glb, 'SELECT pg_backend_pid()')

            def kill_soon():
                time.sleep(0.4)
                with admin.cursor() as cur:
                    cur.execute('SELECT pg_terminate_backend(%s)', (pid,))

            killer = threading.Thread(target=kill_soon)
            killer.start()
            started = time.monotonic()
            with pytest.raises(psycopg2.OperationalError):
                glb._execute_plan(_plan(['SELECT pg_sleep(2)'], read_only=True))
            elapsed = time.monotonic() - started
            killer.join(5)
            assert elapsed < 1.9, 'the interrupted statement was re-run'
            assert glb._run_query('MATCH (p:Person) RETURN count(p) AS c') == [{'c': 3}]
        finally:
            admin.close()
            glb.endGlobal()

    def test_end_global_closes_every_session(self, rr_env, age_graph, monkeypatch):
        module = sys.modules[rr_env.iglobal_cls.__module__]
        opened = []
        real_open = module._open_connection
        monkeypatch.setattr(module, '_open_connection', lambda dsn: opened.append(real_open(dsn)) or opened[-1])
        glb = _begin(rr_env)
        barrier = threading.Barrier(3)

        def call():
            barrier.wait()
            return glb._execute_plan(_plan(['SELECT pg_sleep(0.2)', 'SELECT pg_backend_pid()'], read_only=True))[0][0]

        results, errors = _run_threads({i: call for i in range(3)})
        assert not errors, errors
        pids = sorted(set(results.values()))
        glb.endGlobal()
        assert opened and all(conn.closed for conn in opened)
        if not BEHIND_POOLER:
            admin = _admin()
            try:
                deadline = time.monotonic() + 5
                alive = pids
                while alive and time.monotonic() < deadline:
                    with admin.cursor() as cur:
                        cur.execute('SELECT pid FROM pg_stat_activity WHERE pid = ANY(%s)', (pids,))
                        alive = [r[0] for r in cur.fetchall()]
                    time.sleep(0.1)
                assert alive == []
            finally:
                admin.close()
        with pytest.raises(Exception):
            glb._run_query('MATCH (p:Person) RETURN count(p) AS c')
