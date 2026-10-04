# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Live tests for graph_neo4j's read_query / execute(shape='graph') against a real Neo4j 5.

The node runs with the real ``neo4j`` driver and the real shared graph base;
only the engine surface (rocketlib, config resolution) is stubbed. Every
refused write is proven by database state before and after, not by the error
text alone.

Configuration (defaults are the local disposable container):
    RR_TEST_NEO4J_URI       bolt://127.0.0.1:57687
    RR_TEST_NEO4J_USER      neo4j
    RR_TEST_NEO4J_PASSWORD  gxlocal-test-pass
    RR_TEST_NEO4J_READONLY_URI / _USER / _PASSWORD
                            optional: an identity whose DATABASE ROLE is read-only
                            (Neo4j Enterprise or Aura). Without it the role test
                            is reported as skipped (NOT RUN), never as passed.

Skips when the server is unreachable unless RR_REQUIRE_DB_TESTS is set.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

from pathlib import Path

import pytest

_REQUIRED = bool(os.environ.get('RR_REQUIRE_DB_TESTS'))
for _name in [n for n in sys.modules if n.split('.')[0] == 'neo4j']:
    if not getattr(sys.modules[_name], '__file__', None):
        del sys.modules[_name]
if _REQUIRED:
    import neo4j
else:
    neo4j = pytest.importorskip('neo4j')

_REPO = Path(__file__).resolve().parents[2]
_AI_SRC = _REPO / 'packages' / 'ai' / 'src'
_GRAPH_PKG = _AI_SRC / 'ai' / 'common' / 'graph'
_UTILS_DIR = _AI_SRC / 'ai' / 'common' / 'utils'

URI = os.environ.get('RR_TEST_NEO4J_URI', 'bolt://127.0.0.1:57687')
USER = os.environ.get('RR_TEST_NEO4J_USER', 'neo4j')
PASSWORD = os.environ.get('RR_TEST_NEO4J_PASSWORD', 'gxlocal-test-pass')


def _reachable() -> bool:
    try:
        with neo4j.GraphDatabase.driver(URI, auth=(USER, PASSWORD), connection_timeout=3) as d:
            d.verify_connectivity()
        return True
    except Exception:
        return False


_REACHABLE = _reachable()
if _REQUIRED and not _REACHABLE:
    pytest.fail(f'RR_REQUIRE_DB_TESTS is set but Neo4j is not reachable at {URI}', pytrace=False)
pytestmark = pytest.mark.skipif(not _REACHABLE, reason=f'Neo4j test server not reachable at {URI}')


# ---------------------------------------------------------------------------
# Loading a graph node with the real base and driver (shared with the
# FalkorDB live suite)
# ---------------------------------------------------------------------------


def _load_from_path(name: str, path: Path, *, is_package: bool = False):
    search = [str(path.parent)] if is_package else None
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=search)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_graph_node(monkeypatch, node: str):
    """Stub the engine surface, load the real graph package and ``nodes/<node>``.

    Returns a namespace with the IGlobal/IInstance classes and a list that
    collects warning() calls.
    """
    warnings: list = []
    rocketlib = types.ModuleType('rocketlib')
    rocketlib.IGlobalBase = type('IGlobalBase', (), {})
    rocketlib.IInstanceBase = type('IInstanceBase', (), {})
    rocketlib.tool_function = lambda **kwargs: lambda f: f
    rocketlib.debug = lambda *a, **kw: None
    rocketlib.error = lambda *a, **kw: None
    rocketlib.warning = warnings.append
    rocketlib.OPEN_MODE = types.SimpleNamespace(CONFIG='config', RUN='run')
    rocketlib_types = types.ModuleType('rocketlib.types')
    rocketlib_types.IInvokeLLM = types.SimpleNamespace(Ask=lambda **kw: kw)
    rocketlib.types = rocketlib_types
    monkeypatch.setitem(sys.modules, 'rocketlib', rocketlib)
    monkeypatch.setitem(sys.modules, 'rocketlib.types', rocketlib_types)

    ai_pkg = types.ModuleType('ai')
    ai_pkg.__path__ = []
    common_pkg = types.ModuleType('ai.common')
    common_pkg.__path__ = [str(_AI_SRC / 'ai' / 'common')]
    schema = types.ModuleType('ai.common.schema')
    schema.Answer = type('Answer', (), {'setAnswer': lambda self, v: setattr(self, 'value', v)})
    schema.Question = type('Question', (), {})
    schema.QuestionType = types.SimpleNamespace(QUESTION=1, DIALECT=2, EXECUTE=3)
    table = types.ModuleType('ai.common.table')
    table.Table = types.SimpleNamespace(generate_markdown_table=lambda data, headers=None: str(data))
    config = types.ModuleType('ai.common.config')
    config.Config = types.SimpleNamespace(getNodeConfig=lambda provider, conn: dict(conn))
    for name, module in (
        ('ai', ai_pkg),
        ('ai.common', common_pkg),
        ('ai.common.schema', schema),
        ('ai.common.table', table),
        ('ai.common.config', config),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    config_utils = _load_from_path('ai.common.config_utils', _UTILS_DIR / 'config_utils.py')
    tool_args = _load_from_path('ai.common.tool_args', _UTILS_DIR / 'tool_args.py')
    utils = types.ModuleType('ai.common.utils')
    utils.parse_bool = config_utils.parse_bool
    utils.config_int = config_utils.config_int
    for fn in ('normalize_tool_input', 'require_str', 'require_dict', 'require_int', 'optional_int', 'optional_str'):
        setattr(utils, fn, getattr(tool_args, fn))
    monkeypatch.setitem(sys.modules, 'ai.common.utils', utils)

    for name in list(sys.modules):
        if name == 'ai.common.graph' or name.startswith(('ai.common.graph.', f'nodes.{node}')):
            monkeypatch.delitem(sys.modules, name)
    graph_pkg = _load_from_path('ai.common.graph', _GRAPH_PKG / '__init__.py', is_package=True)
    monkeypatch.setitem(sys.modules, 'ai.common.graph', graph_pkg)

    node_dir = _REPO / 'nodes' / 'src' / 'nodes' / node
    pkg = types.ModuleType(f'nodes.{node}')
    pkg.__path__ = [str(node_dir)]
    monkeypatch.setitem(sys.modules, f'nodes.{node}', pkg)
    iglobal = _load_from_path(f'nodes.{node}.IGlobal', node_dir / 'IGlobal.py')
    pkg.IGlobal = iglobal
    iinstance = _load_from_path(f'nodes.{node}.IInstance', node_dir / 'IInstance.py')
    errors = sys.modules['ai.common.graph.graph_errors']
    return types.SimpleNamespace(
        iglobal_cls=iglobal.IGlobal,
        iinstance_cls=iinstance.IInstance,
        iglobal_module=iglobal,
        GraphToolError=errors.GraphToolError,
        warnings=warnings,
    )


def start_node(env, logical_type: str, config: dict):
    glb = env.iglobal_cls()
    glb.glb = types.SimpleNamespace(logicalType=logical_type, connConfig=dict(config))
    glb.IEndpoint = types.SimpleNamespace(endpoint=types.SimpleNamespace(openMode='run'))
    glb.beginGlobal()
    inst = env.iinstance_cls()
    inst.IGlobal = glb
    return glb, inst


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED = """
CREATE (a:GxPerson {name: 'Alice', age: 37, big: 9007199254740993, born: date('1989-02-28'),
                    seen: datetime({year: 2026, month: 10, day: 4, hour: 12, timezone: 'Europe/Berlin'}),
                    tenure: duration('P1Y2M3DT4.5S'), home: point({longitude: 13.405, latitude: 52.52}),
                    meta: '{"@kind": "node"}'}),
       (b:GxPerson {name: 'Bob', age: 41}),
       (c:GxCompany {name: 'Acme'}),
       (a)-[:GX_KNOWS {since: 2019}]->(b),
       (a)-[:GX_KNOWS {since: 2021}]->(b),
       (b)-[:GX_KNOWS {since: 2020}]->(a),
       (a)-[:GX_LIKES]->(a),
       (a)-[:GX_WORKS_AT {role: 'eng'}]->(c)
SET a:GxEmployee
"""
CLEANUP = "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Gx') DETACH DELETE n"


@pytest.fixture()
def neo_db():
    driver = neo4j.GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session(database='neo4j') as s:
        s.run(CLEANUP).consume()
        s.run(SEED).consume()
        s.run('CREATE (:GxBlob {b: $b})', b=bytearray(b'\x00\xffraw')).consume()
    yield driver
    with driver.session(database='neo4j') as s:
        s.run(CLEANUP).consume()
    driver.close()


@pytest.fixture()
def neo_env(monkeypatch):
    return load_graph_node(monkeypatch, 'graph_neo4j')


def _start(neo_env, **config):
    return start_node(
        neo_env,
        'graph_neo4j',
        {'uri': URI, 'user': USER, 'password': PASSWORD, 'database': 'neo4j', **config},
    )


def _count(driver, cypher='MATCH (n) RETURN count(n) AS c'):
    with driver.session(database='neo4j') as s:
        return s.run(cypher).single()['c']


def _labels(driver):
    with driver.session(database='neo4j') as s:
        return sorted(r['label'] for r in s.run('CALL db.labels() YIELD label RETURN label'))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReadQueryShape:
    def test_entities_ids_and_stored_direction(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            out = inst.read_query(
                {
                    'cypher': "MATCH (a:GxPerson {name: 'Alice'})-[r]->(m) RETURN a, r, m ORDER BY type(r), r.since",
                    'limit': 10,
                }
            )
            assert out['columns'] == ['a', 'r', 'm']
            assert out['truncated'] is False and out['row_limit'] == 10
            alice = out['rows'][0][0]
            assert alice['@kind'] == 'node' and alice['labels'] == ['GxEmployee', 'GxPerson']
            assert isinstance(alice['id'], str) and alice['id'].count(':') == 2  # elementId
            assert alice['properties']['big'] == {'@kind': 'number', 'value': '9007199254740993'}
            assert alice['properties']['born'] == {'@kind': 'temporal', 'type': 'date', 'value': '1989-02-28'}
            assert alice['properties']['seen']['type'] == 'datetime'
            assert alice['properties']['seen']['zone'] == 'Europe/Berlin'
            assert alice['properties']['tenure'] == {'@kind': 'temporal', 'type': 'duration', 'value': 'P1Y2M3DT4.5S'}
            assert alice['properties']['home'] == {'@kind': 'point', 'srid': 4326, 'coordinates': [13.405, 52.52]}
            rels = [row[1] for row in out['rows']]
            assert [r['type'] for r in rels] == ['GX_KNOWS', 'GX_KNOWS', 'GX_LIKES', 'GX_WORKS_AT']
            knows1, knows2, likes = rels[0], rels[1], rels[2]
            assert knows1['id'] != knows2['id']  # parallel relationships stay distinct
            assert knows1['start'] == alice['id'] and knows1['end'] == out['rows'][0][2]['id']
            assert likes['start'] == likes['end'] == alice['id']  # self loop
        finally:
            glb.endGlobal()

    def test_path_keeps_traversal_order_and_stored_direction(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            out = inst.read_query(
                {'cypher': "MATCH p = (b:GxPerson {name: 'Bob'})<-[:GX_KNOWS {since: 2019}]-(a) RETURN p"}
            )
            path = out['rows'][0][0]
            assert [n['properties']['name'] for n in path['nodes']] == ['Bob', 'Alice']
            rel = path['relationships'][0]
            assert rel['start'] == path['nodes'][1]['id'] and rel['end'] == path['nodes'][0]['id']
        finally:
            glb.endGlobal()

    def test_element_id_round_trips_as_a_parameter(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            alice = inst.read_query({'cypher': "MATCH (a:GxPerson {name: 'Alice'}) RETURN a"})['rows'][0][0]
            out = inst.read_query(
                {'cypher': 'MATCH (n) WHERE elementId(n) = $id RETURN n.name', 'params': {'id': alice['id']}}
            )
            assert out['rows'] == [['Alice']]
        finally:
            glb.endGlobal()

    def test_binary_property_does_not_fail_the_query(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            out = inst.read_query({'cypher': 'MATCH (n:GxBlob) RETURN n.b'})
            assert out['rows'] == [[{'@kind': 'bytes', 'size': 5, 'base64': 'AP9yYXc='}]]
        finally:
            glb.endGlobal()

    def test_odd_string_parameters_are_bound_not_spliced(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            tricky = 'x\' RETURN 1 // " \\ `'
            out = inst.read_query({'cypher': 'RETURN $s AS s, $n AS n', 'params': {'s': tricky, 'n': None}})
            assert out['rows'] == [[tricky, None]]
        finally:
            glb.endGlobal()


WRITES = [
    "CREATE (:GxEvil {name: 'x'})",
    "MERGE (:GxEvil {name: 'x'})",
    "MATCH (a:GxPerson {name: 'Alice'}) SET a:GxEvil",
    "MATCH (a:GxPerson {name: 'Bob'}) DETACH DELETE a",
    "CALL db.createLabel('GxEvilLabel')",
    "CALL `db`.`createLabel`('GxEvilLabel')",
    'MATCH (a:GxPerson) CALL { WITH a CREATE (:GxEvil) } RETURN count(*)',
    'FOREACH (x IN [1] | CREATE (:GxEvil))',
    "CALL apoc.create.node(['GxEvil'], {})",
]


class TestReadOnlyInvariant:
    @pytest.mark.parametrize('allow_execute', [False, True])
    @pytest.mark.parametrize('statement', WRITES)
    def test_writes_refused_with_state_unchanged(self, neo_env, neo_db, allow_execute, statement):
        glb, inst = _start(neo_env, allow_execute=allow_execute)
        try:
            before = (_count(neo_db), _labels(neo_db))
            with pytest.raises(neo_env.GraphToolError) as err:
                inst.read_query({'cypher': statement})
            assert str(err.value).startswith('Refused: ')
            assert (_count(neo_db), _labels(neo_db)) == before
        finally:
            glb.endGlobal()

    def test_read_session_refuses_writes_even_without_the_lexical_check(self, neo_env, neo_db, monkeypatch):
        # Defence in depth, layer 2: with the token check disabled, the
        # READ-mode transaction still refuses (single instance, 5.x). This is
        # not the security boundary; the database role is.
        monkeypatch.setattr(neo_env.iglobal_module, 'check_read_only_cypher', lambda *a, **kw: None)
        glb, inst = _start(neo_env, allow_execute=True)
        try:
            before = (_count(neo_db), _labels(neo_db))
            for statement in ("CREATE (:GxEvil {name: 'x'})", "CALL db.createLabel('GxEvilLabel')"):
                with pytest.raises(neo_env.GraphToolError) as err:
                    inst.read_query({'cypher': statement})
                assert str(err.value).startswith('Refused: the database refused a write')
                assert 'read access mode' in str(err.value)
            assert (_count(neo_db), _labels(neo_db)) == before
        finally:
            glb.endGlobal()

    def test_natural_language_read_path_uses_the_same_check(self, neo_env, neo_db):
        # get_data runs LLM-written Cypher through _run_query: the legacy
        # keyword gate let procedure writes through; the token check does not.
        glb, inst = _start(neo_env)
        try:
            before = (_count(neo_db), _labels(neo_db))
            with pytest.raises(ValueError, match='Refused: CALL db.createLabel'):
                glb._run_query("CALL db.createLabel('GxEvilLabel')")
            assert (_count(neo_db), _labels(neo_db)) == before
        finally:
            glb.endGlobal()

    def test_allowlisted_procedures_run(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            out = inst.read_query({'cypher': 'CALL `db`.`labels`() YIELD label RETURN label ORDER BY label'})
            assert ['GxPerson'] in out['rows']
            # Case variants pass the allowlist (it compares case-insensitively)
            # but Neo4j procedure names are case-sensitive, so they cannot reach
            # any other procedure: the server just reports it unknown.
            with pytest.raises(neo_env.GraphToolError, match='no procedure with the name'):
                inst.read_query({'cypher': 'CALL DB.LABELS()'})
        finally:
            glb.endGlobal()

    def test_database_role_boundary(self, neo_env, neo_db):
        uri = os.environ.get('RR_TEST_NEO4J_READONLY_URI')
        if not uri:
            pytest.skip(
                'NOT RUN: needs RR_TEST_NEO4J_READONLY_URI/_USER/_PASSWORD for a read-only database role '
                '(Neo4j Enterprise or Aura); Community has no roles'
            )
        glb, inst = start_node(
            neo_env,
            'graph_neo4j',
            {
                'uri': uri,
                'user': os.environ.get('RR_TEST_NEO4J_READONLY_USER', ''),
                'password': os.environ.get('RR_TEST_NEO4J_READONLY_PASSWORD', ''),
                'database': 'neo4j',
                'allow_execute': True,
            },
        )
        try:
            before = _count(neo_db)
            with pytest.raises(Exception):
                inst.execute({'query': "CREATE (:GxEvil {name: 'role'})"})
            assert _count(neo_db) == before
        finally:
            glb.endGlobal()


class TestLimitsAndBudgets:
    def test_exact_limit_and_truncation(self, neo_env, neo_db):
        glb, inst = _start(neo_env)
        try:
            q = 'MATCH (p:GxPerson) RETURN p.name ORDER BY p.name'
            exact = inst.read_query({'cypher': q, 'limit': 2})
            assert exact['rows'] == [['Alice'], ['Bob']] and exact['truncated'] is False
            cut = inst.read_query({'cypher': q, 'limit': 1})
            assert cut['rows'] == [['Alice']] and cut['truncated'] is True and cut['truncated_by'] == 'rows'
        finally:
            glb.endGlobal()

    def test_collect_is_bounded_by_the_element_budget(self, neo_env, neo_db):
        with neo_db.session(database='neo4j') as s:
            s.run('UNWIND range(1, 10050) AS i CREATE (:GxBulk {i: i})').consume()
        glb, inst = _start(neo_env)
        try:
            with pytest.raises(neo_env.GraphToolError, match='first row holds more than 10,000 graph elements'):
                inst.read_query({'cypher': 'MATCH (n:GxBulk) RETURN collect(n)'})
            out = inst.read_query(
                {
                    'cypher': 'UNWIND [0, 1] AS k MATCH (n:GxBulk) WITH k, collect(n)[0..6000] AS c RETURN k, c ORDER BY k'
                }
            )
            assert len(out['rows']) == 1 and out['truncated_by'] == 'elements' and out['elements'] == 6000
        finally:
            glb.endGlobal()

    def test_server_deadline(self, neo_env, neo_db, monkeypatch):
        monkeypatch.setattr(neo_env.iglobal_cls, 'QUERY_TIMEOUT', 0.5)
        glb, inst = _start(neo_env)
        try:
            with pytest.raises(neo_env.GraphToolError) as err:
                inst.read_query(
                    {'cypher': 'UNWIND range(1, 200000000) AS x WITH x WHERE x % 7 = 0 RETURN count(x)', 'limit': 1}
                )
            assert str(err.value).startswith('Query timed out after 500 ms')
        finally:
            glb.endGlobal()


class TestExecuteGraphShape:
    def test_graph_shape_write_when_allowed(self, neo_env, neo_db):
        glb, inst = _start(neo_env, allow_execute=True)
        try:
            out = inst.execute({'query': "CREATE (n:GxNew {name: 'n1'}) RETURN n", 'shape': 'graph'})
            assert out['rows'][0][0]['labels'] == ['GxNew'] and out['affected_rows'] >= 2
            assert _count(neo_db, 'MATCH (n:GxNew) RETURN count(n) AS c') == 1
            legacy = inst.execute({'query': 'MATCH (n:GxNew) RETURN n.name AS name'})
            assert legacy == {'rows': [{'name': 'n1'}], 'affected_rows': 0}
        finally:
            glb.endGlobal()

    def test_refused_when_execute_is_off(self, neo_env, neo_db):
        glb, inst = _start(neo_env, allow_execute=False)
        try:
            before = _count(neo_db)
            with pytest.raises(ValueError, match='execute tool is disabled'):
                inst.execute({'query': "CREATE (:GxNew {name: 'n2'})", 'shape': 'graph'})
            assert _count(neo_db) == before
        finally:
            glb.endGlobal()
