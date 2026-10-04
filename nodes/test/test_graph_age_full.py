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


# ---------------------------------------------------------------------------
# read_query / execute(shape='graph') through the node's tools
# ---------------------------------------------------------------------------


def _instance(rr_env, glb):
    inst = rr_env.iinstance_cls()
    inst.IGlobal = glb
    return inst


def _graph_tool_error():
    return sys.modules['ai.common.graph.graph_errors'].GraphToolError


def _age_state():
    """Vertex/edge counts and the label catalog of THIS run's graph, read directly.

    Scoped to the test's own graph (other runs may create graphs concurrently);
    the graph must still exist, so a dropped graph also shows up as a change.
    """
    from .test_rocketride_graph_full import GRAPH

    conn = _admin()
    try:
        with conn.cursor() as cur:
            cur.execute('SET search_path = ag_catalog, "$user", public')
            cur.execute(f"SELECT count(*) FROM cypher('{GRAPH}', $$ MATCH (n) RETURN n $$) AS (n agtype)")
            vertices = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM cypher('{GRAPH}', $$ MATCH ()-[r]->() RETURN r $$) AS (r agtype)")
            edges = cur.fetchone()[0]
            cur.execute(
                'SELECT l.name FROM ag_label l JOIN ag_graph g ON l.graph = g.graphid WHERE g.name = %s ORDER BY 1',
                (GRAPH,),
            )
            labels = [r[0] for r in cur.fetchall()]
        return vertices, edges, labels
    finally:
        conn.close()


def _cypher_admin(statement):
    from .test_rocketride_graph_full import GRAPH

    conn = _admin()
    try:
        with conn.cursor() as cur:
            cur.execute('SET search_path = ag_catalog, "$user", public')
            cur.execute(f"SELECT * FROM cypher('{GRAPH}', $$ {statement} $$) AS (v agtype)")
            return cur.fetchall()
    finally:
        conn.close()


AGE_WRITES = [
    "CREATE (:Evil {name: 'x'})",
    "MERGE (:Evil {name: 'x'})",
    "MATCH (p:Person {name: 'alice'}) SET p.evil = true",
    "MATCH (p:Person {name: 'bob'}) DETACH DELETE p",
    'MATCH (p:Person) REMOVE p.age',
    'RETURN pg_catalog.sqrt(25)',
    'CALL db.labels()',
]


class TestReadQuery:
    def test_shape_duplicate_columns_and_direction(self, rr_env, age_graph):
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            out = inst.read_query(
                {'cypher': "MATCH (a:Person {name: 'alice'})-[r:KNOWS]->(b) RETURN a, r, b, a.name, a.name"}
            )
            assert out['columns'] == ['a', 'r', 'b', 'a.name', 'a.name']
            a, r, b, n1, n2 = out['rows'][0]
            assert (n1, n2) == ('alice', 'alice')
            assert a['labels'] == ['Person'] and r['type'] == 'KNOWS'
            assert (r['start'], r['end']) == (a['id'], b['id'])
            assert int(a['id']) > 0 and isinstance(a['id'], str)
            path = inst.read_query({'cypher': "MATCH p = (b:Person {name: 'bob'})<-[:KNOWS]-(a) RETURN p"})['rows'][0][
                0
            ]
            assert [n['properties']['name'] for n in path['nodes']] == ['bob', 'alice']
            rel = path['relationships'][0]
            assert (rel['start'], rel['end']) == (path['nodes'][1]['id'], path['nodes'][0]['id'])
        finally:
            glb.endGlobal()

    def test_ids_beyond_2_53_round_trip_as_string_parameters(self, rr_env, age_graph):
        for i in range(36):
            _cypher_admin(f'CREATE (:L{i} {{k: {i}}})')
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            node = inst.read_query({'cypher': 'MATCH (n:L35) RETURN n'})['rows'][0][0]
            assert int(node['id']) > 2**53
            out = inst.read_query(
                {'cypher': 'MATCH (n) WHERE id(n) = toInteger($id) RETURN n.k', 'params': {'id': node['id']}}
            )
            assert out['rows'] == [[35]]
        finally:
            glb.endGlobal()

    @pytest.mark.parametrize('allow_execute', [False, True])
    @pytest.mark.parametrize('statement', AGE_WRITES)
    def test_writes_refused_with_state_unchanged(self, rr_env, age_graph, allow_execute, statement):
        glb = _begin(rr_env, {'allow_execute': allow_execute})
        inst = _instance(rr_env, glb)
        try:
            before = _age_state()
            with pytest.raises(_graph_tool_error()) as err:
                inst.read_query({'cypher': statement})
            assert str(err.value).startswith('Refused: ')
            assert _age_state() == before
        finally:
            glb.endGlobal()

    def test_hints_are_raised_before_the_database(self, rr_env, age_graph, monkeypatch):
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        sent = []
        monkeypatch.setattr(glb, '_execute_plan', lambda *a, **kw: sent.append(a))
        try:
            with pytest.raises(_graph_tool_error()) as err:
                inst.read_query({'cypher': "RETURN date('2024-01-01')"})
            headline, _, detail = str(err.value).partition('\n')
            assert headline == 'Not supported on Apache AGE 1.5.0: date()'
            assert 'ISO-8601' in detail
            assert sent == []
        finally:
            glb.endGlobal()

    def test_exact_limit_and_truncation(self, rr_env, age_graph):
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            q = 'MATCH (p:Person) RETURN p.name ORDER BY p.name'
            exact = inst.read_query({'cypher': q, 'limit': 3})
            assert [r[0] for r in exact['rows']] == ['alice', 'bob', 'carol'] and exact['truncated'] is False
            cut = inst.read_query({'cypher': q, 'limit': 2})
            assert len(cut['rows']) == 2 and cut['truncated'] is True and cut['truncated_by'] == 'rows'
        finally:
            glb.endGlobal()

    def test_collect_is_bounded_by_the_element_budget(self, rr_env, age_graph):
        _cypher_admin('UNWIND range(1, 10050) AS i CREATE (:Bulk {i: i})')
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            with pytest.raises(_graph_tool_error(), match='first row holds more than 10,000 graph elements'):
                inst.read_query({'cypher': 'MATCH (n:Bulk) RETURN collect(n)'})
        finally:
            glb.endGlobal()

    def test_server_deadline(self, rr_env, age_graph):
        _cypher_admin('UNWIND range(1, 2000) AS i CREATE (:Bulk {i: i})')
        glb = _begin(rr_env, {'query_timeout_ms': 200})
        inst = _instance(rr_env, glb)
        try:
            with pytest.raises(_graph_tool_error()) as err:
                inst.read_query({'cypher': 'MATCH (a:Bulk), (b:Bulk), (c:Bulk) RETURN count(*)'})
            assert str(err.value).startswith('Query timed out after 200 ms')
        finally:
            glb.endGlobal()

    def test_execute_graph_shape(self, rr_env, age_graph):
        glb = _begin(rr_env, {'allow_execute': True})
        inst = _instance(rr_env, glb)
        try:
            out = inst.execute({'query': "CREATE (n:Person {name: 'dora'}) RETURN n", 'shape': 'graph'})
            assert out['rows'][0][0]['labels'] == ['Person'] and out['affected_rows'] == 1
            assert inst.read_query({'cypher': "MATCH (p:Person {name: 'dora'}) RETURN count(p)"})['rows'] == [[1]]
        finally:
            glb.endGlobal()


class TestCapabilityProbes:
    """The capability table's REJECT cells hold on the live AGE version.

    Each construct is sent straight to AGE (bypassing the translator) and must
    fail there. If an AGE upgrade starts accepting one, this fails and the
    table needs a reviewed update.
    """

    @pytest.mark.parametrize(
        'statement',
        [
            "RETURN date('2024-01-01')",
            'RETURN time()',
            'RETURN localtime()',
            "RETURN localdatetime('2024-01-01T00:00:00')",
            "RETURN duration('P1D')",
            "RETURN datetime('2024-01-01T00:00:00Z')",
            'MATCH (n) RETURN elementId(n)',
            'RETURN [x IN [1, 2] | x * 2]',
            'RETURN [x IN [1, 2] WHERE x > 1]',
            'MATCH (n) RETURN [(n)-->(m) | m]',
            'MATCH (a:Person), (b:Person) RETURN allShortestPaths((a)-[*..3]-(b))',
            'MATCH (n) WHERE EXISTS { MATCH (n)-->() } RETURN n',
            'MATCH p = shortestPath((a:Person)-[*..3]-(b:Person)) RETURN p',
            'MATCH (n:Person:Company) RETURN n',
        ],
    )
    def test_rejected_construct_fails_on_live_age(self, rr_env, age_graph, statement):
        with pytest.raises(psycopg2.Error):
            _cypher_admin(statement)

    @pytest.mark.parametrize('statement', ['RETURN timestamp()', 'RETURN toString(1)', 'MATCH (n) RETURN keys(n)'])
    def test_supported_construct_runs_on_live_age(self, rr_env, age_graph, statement):
        _cypher_admin(statement)


class TestSchemaAndDialect:
    def test_refresh_contents_and_estimated_counts(self, rr_env, age_graph):
        from .test_rocketride_graph_full import GRAPH

        _cypher_admin(
            "MATCH (a:Person {name: 'carol'}) CREATE (a)-[:WORKS_AT {since: 2024}]->(:Company {name: 'Beta'})"
        )
        conn = _admin()
        try:
            with conn.cursor() as cur:
                cur.execute(f'ANALYZE "{GRAPH}"."Person"')
                cur.execute(f'ANALYZE "{GRAPH}"."KNOWS"')
        finally:
            conn.close()
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            block = inst.refresh_schema({})['schema']
            labels = {label['name']: label for label in block['labels']}
            assert set(labels) == {'Person', 'Company'}
            assert labels['Person']['count'] == 3 and labels['Person']['count_estimated'] is True
            assert {p['name']: p['types'] for p in labels['Person']['properties']} == {
                'age': ['integer'],
                'name': ['string'],
            }
            rels = {r['type']: r for r in block['relationship_types']}
            assert rels['KNOWS']['endpoints'] == [{'start': 'Person', 'end': 'Person', 'observed': True}]
            assert rels['KNOWS']['properties'] == [{'name': 'since', 'types': ['integer']}]
            assert rels['KNOWS']['count'] == 2 and rels['KNOWS']['count_estimated'] is True
            works = rels['WORKS_AT']
            assert works['endpoints'] == [{'start': 'Person', 'end': 'Company', 'observed': True}]
            assert works['properties'] == [{'name': 'since', 'types': ['integer']}]
            assert block['error'] is None and block['stale'] is False
        finally:
            glb.endGlobal()

    def test_refresh_shows_a_change_made_by_execute(self, rr_env, age_graph):
        glb = _begin(rr_env, {'allow_execute': True})
        inst = _instance(rr_env, glb)
        try:
            inst.execute({'query': "CREATE (:Later {k: 1})-[:LATER_REL {w: 1.5}]->(:Person {name: 'z'})"})
            assert 'Later' not in inst.get_schema({})['labels']
            out = inst.refresh_schema({})
            assert 'Later' in out['labels']
            later = {r['type']: r for r in out['schema']['relationship_types']}['LATER_REL']
            assert later['endpoints'] == [{'start': 'Later', 'end': 'Person', 'observed': True}]
            assert later['properties'] == [{'name': 'w', 'types': ['float']}]
        finally:
            glb.endGlobal()

    def test_refresh_beside_reads_and_an_uncommitted_write(self, rr_env, age_graph):
        glb = _begin(rr_env, {'allow_execute': True})
        inst = _instance(rr_env, glb)
        age = _age()
        write = glb._translate('CREATE (:Uncommitted {k: 1})', mode=age.TranslateMode.RAW)
        write.statements.append('SELECT pg_sleep(1.0)')
        write.binds.append(())
        write.result_index = len(write.statements) - 1
        started = threading.Event()

        def run_write():
            started.set()
            return glb._execute_plan(write, fetch_cap=1)

        def run_refresh():
            started.wait(5)
            time.sleep(0.4)  # inside the writer's transaction, before its COMMIT
            return inst.refresh_schema({})['schema']

        def run_read():
            started.wait(5)
            time.sleep(0.4)
            return inst.read_query({'cypher': 'MATCH (p:Person) RETURN count(p)'})['rows']

        try:
            results, errors = _run_threads({'write': run_write, 'refresh': run_refresh, 'read': run_read})
            assert not errors, errors
            assert 'Uncommitted' not in {label['name'] for label in results['refresh']['labels']}
            assert results['read'] == [[3]]
            assert 'Uncommitted' in inst.refresh_schema({})['labels']  # visible once committed
        finally:
            glb.endGlobal()

    def test_failed_refresh_keeps_the_last_good_schema(self, rr_env, age_graph, monkeypatch):
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            good = inst.get_schema({})['schema']
            monkeypatch.setattr(sys.modules['ai.common.graph.graph_global_base'], 'SCHEMA_REFRESH_BUDGET_MS', 0)
            stale = inst.refresh_schema({})['schema']
            assert stale['stale'] is True and stale['error'] and stale['labels'] == good['labels']
        finally:
            glb.endGlobal()

    def test_dialect_and_prompt(self, rr_env, age_graph):
        glb = _begin(rr_env)
        inst = _instance(rr_env, glb)
        try:
            out = inst.dialect({})
            assert out['engine']['version'] == '1.5.0' and out['capabilities']['shortest_path'] is False
            assert out['read_boundary'] == 'read_only_tx' and out['limits']['statement_timeout_ms'] == 30000
            rules = ' '.join(glb._prompt_rules())
            assert 'Apache AGE 1.5.0' in rules and 'elementId()' in rules and 'at most 10' in rules
        finally:
            glb.endGlobal()
