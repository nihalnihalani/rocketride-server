# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Self-tests for the acceptance harness's own verdict logic.

They need no engine, database or browser: the SDK and the Neo4j driver are
replaced by small in-memory stand-ins written to a temporary directory. They
check that a harness check cannot pass without testing anything, and that the
Neo4j clean-up stays inside the run's label.

Run: python3 -m unittest discover -s scripts/acceptance/graph-explorer/selftest -v
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest

from pathlib import Path

ACC = Path(__file__).resolve().parent.parent

# A stand-in for the rocketride SDK, enough for graph_lifecycle.py. FAKE_RESTART_MODE
# 'window' makes calls fail with TASK_STOPPED for a moment after restart(); 'none'
# restarts instantly, so a caller never sees the restart window.
FAKE_SDK = textwrap.dedent(
    """
    import asyncio
    import os
    import time
    import uuid


    class CommandException(RuntimeError):
        def __init__(self, message, code=None):
            super().__init__(message)
            self.code = code


    class RocketRideClient:
        def __init__(self, uri=None, auth=None, **_):
            self.tasks = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def use(self, pipeline, source):
            token = uuid.uuid4().hex
            wired = any(c.get('control') for c in pipeline['components'])
            self.tasks[token] = {'project_id': pipeline['project_id'], 'source': source, 'wired': wired, 'stopped_until': 0.0}
            return {'token': token}

        async def get_tasks(self):
            return [{'token': t, 'source': v['source'], 'pipeline': {'project_id': v['project_id']}} for t, v in self.tasks.items()]

        async def tool(self, token, tool, node_id='', input=None, timeout=None):
            await asyncio.sleep(0)
            task = self.tasks.get(token)
            if task is None:
                raise CommandException('Task not registered', 'TASK_NOT_REGISTERED')
            if time.monotonic() < task['stopped_until']:
                raise CommandException('Task is stopping', 'TASK_STOPPED')
            if not task['wired']:
                raise CommandException(f'Node "{node_id}" not found in pipeline')
            return {'dialect': 'falkordb'}

        async def terminate(self, token):
            self.tasks.pop(token, None)

        async def restart(self, project_id, source, pipeline, token=None, team_id=None):
            if os.environ.get('FAKE_RESTART_MODE') == 'window':
                self.tasks[token]['stopped_until'] = time.monotonic() + 0.5
    """
)


def _write_fake_sdk(root: Path) -> Path:
    pkg = root / 'rocketride'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text(FAKE_SDK)
    return root


class ValidateAllExitCode(unittest.TestCase):
    """validate_all.sh must report a failed gate in its exit status."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='gx-selftest-'))
        repo = self.tmp / 'repo'
        (repo / 'scripts').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        builder = repo / 'builder'
        builder.write_text('#!/bin/sh\nexit "${FAKE_RC:-0}"\n')
        builder.chmod(0o755)
        (repo / 'scripts' / 'validate-node-readme.py').write_text(
            "import os, sys\nsys.exit(int(os.environ.get('FAKE_RC', '0')))\n"
        )
        (repo / 'scripts' / 'build.js').write_text("process.exit(Number(process.env.FAKE_RC || '0'));\n")
        self.repo = repo

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_gates(self, rc: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, FAKE_RC=rc, OUT_DIR=str(self.tmp / 'out'), STORE_DIR=str(self.tmp / 'store'))
        return subprocess.run(
            ['bash', str(ACC / 'validate_all.sh')], cwd=self.repo, env=env, capture_output=True, text=True
        )

    def test_failed_gate_exits_non_zero(self):
        res = self.run_gates('1')
        self.assertNotEqual(res.returncode, 0, f'validate_all.sh exited 0 although every gate failed:\n{res.stdout}')

    def test_all_gates_passing_exits_zero(self):
        res = self.run_gates('0')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class LifecycleRestartWindow(unittest.TestCase):
    """graph_lifecycle.py must not pass its restart checks when the window was never observed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='gx-selftest-'))
        _write_fake_sdk(self.tmp / 'stub')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_lifecycle(self, mode: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONPATH=str(self.tmp / 'stub'), FAKE_RESTART_MODE=mode)
        return subprocess.run(
            [sys.executable, str(ACC / 'graph_lifecycle.py'), 'ws://fake.invalid'],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_restart_window_not_observed_fails(self):
        res = self.run_lifecycle('none')
        self.assertNotEqual(
            res.returncode, 0, f'lifecycle passed although no call saw the restart window:\n{res.stdout}{res.stderr}'
        )
        self.assertRegex(res.stdout, r'\[FAIL\] restart: .*TASK_STOPPED')

    def test_restart_window_observed_passes(self):
        res = self.run_lifecycle('window')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class Neo4jCleanupScope(unittest.TestCase):
    """On the shared Neo4j database the acceptance only deletes and counts nodes with its run label."""

    @classmethod
    def setUpClass(cls):
        cls.statements = []
        statements = cls.statements

        class _Driver:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute_query(self, cypher):
                statements.append(cypher)
                return [], None, None

        neo4j = types.ModuleType('neo4j')
        neo4j.GraphDatabase = types.SimpleNamespace(driver=_Driver)
        sdk = types.ModuleType('rocketride')
        sdk.CommandException = type('CommandException', (RuntimeError,), {})
        sdk.RocketRideClient = object
        cls._saved = {name: sys.modules.get(name) for name in ('neo4j', 'rocketride', 'graph_acceptance')}
        sys.modules['neo4j'] = neo4j
        sys.modules['rocketride'] = sdk
        sys.modules.pop('graph_acceptance', None)
        sys.path.insert(0, str(ACC))
        cls.ga = importlib.import_module('graph_acceptance')

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ACC))
        for name, module in cls._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def setUp(self):
        self.statements.clear()

    def assert_scoped(self, statements):
        label = f':{self.ga.RUN}'
        for stmt in statements:
            self.assertIn(label, stmt, f'statement is not limited to the run label {label}: {stmt}')

    def test_reset_deletes_only_run_nodes(self):
        self.ga.Admin('neo4j').reset_and_seed()
        deletes = [s for s in self.statements if 'DELETE' in s.upper()]
        self.assertTrue(deletes)
        self.assert_scoped(deletes)

    def test_intruder_count_is_run_scoped(self):
        self.ga.Admin('neo4j').count('Intruder')
        self.assert_scoped(self.statements)

    def test_write_probes_carry_the_run_label(self):
        probes = self.ga.write_probes('neo4j') + [self.ga.execute_probe('neo4j')]
        self.assertEqual(len(probes), 4)
        self.assert_scoped(probes)

    def test_other_engines_keep_their_own_graph(self):
        probes = self.ga.write_probes('falkordb') + [self.ga.execute_probe('age')]
        self.assertNotIn(f':{self.ga.RUN}', ' '.join(probes))


class FixturePipelines(unittest.TestCase):
    """start_fixtures.py starts what the browser lanes open, and only the write console's fixture may write."""

    GRAPH_PROVIDERS = ('rocketride_graph', 'graph_neo4j', 'graph_falkordb')

    @classmethod
    def setUpClass(cls):
        sdk = types.ModuleType('rocketride')
        sdk.RocketRideClient = object
        cls._saved = {name: sys.modules.get(name) for name in ('rocketride', 'start_fixtures', 'falkordb')}
        sys.modules['rocketride'] = sdk
        sys.modules.pop('start_fixtures', None)
        sys.path.insert(0, str(ACC))
        cls.sf = importlib.import_module('start_fixtures')
        # The display names the Node lanes look for (env.cjs FIXTURES).
        script = 'process.stdout.write(JSON.stringify(require(process.argv[1]).FIXTURES))'
        out = subprocess.run(['node', '-e', script, str(ACC / 'env.cjs')], capture_output=True, text=True, check=True)
        cls.lane_names = json.loads(out.stdout)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ACC))
        for name, module in cls._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_every_fixture_a_lane_opens_is_started(self):
        started = {fixture[0] for fixture in self.sf.FIXTURES}
        self.assertEqual(sorted(set(self.lane_names.values()) - started), [])

    def test_only_the_write_console_fixture_can_write_to_a_graph(self):
        graphs = [f for f in self.sf.FIXTURES if f[2] in self.GRAPH_PROVIDERS]
        writable = [f for f in graphs if f[3].get('allow_execute')]
        self.assertEqual([f[0] for f in writable], [self.lane_names.get('falkordbWrite')])
        _, _, provider, cfg = writable[0]
        self.assertEqual(provider, 'graph_falkordb')
        self.assertEqual(cfg['graph'], self.sf.E.WRITE_GRAPH)
        E = self.sf.E
        self.assertNotIn(cfg['graph'], {E.ACCEPT_GRAPH, E.PERF_GRAPH, E.DEMO_GRAPH})

    def _fake_falkordb(self, graphs):
        queries = []

        class _Graph:
            def __init__(self, name):
                self.name = name

            def query(self, cypher):
                queries.append((self.name, cypher))

        class _FalkorDB:
            def __init__(self, host=None, port=None):
                pass

            def list_graphs(self):
                return list(graphs)

            def select_graph(self, name):
                return _Graph(name)

        module = types.ModuleType('falkordb')
        module.FalkorDB = _FalkorDB
        sys.modules['falkordb'] = module
        return queries

    def test_write_graph_is_created_empty_when_missing(self):
        queries = self._fake_falkordb(graphs=['gx_accept'])
        self.sf.ensure_write_graph()
        self.assertEqual(queries, [(self.sf.E.WRITE_GRAPH, 'CREATE (n) DELETE n')])

    def test_existing_write_graph_is_left_unchanged(self):
        queries = self._fake_falkordb(graphs=['gx_accept', self.sf.E.WRITE_GRAPH])
        self.sf.ensure_write_graph()
        self.assertEqual(queries, [])


if __name__ == '__main__':
    unittest.main()
