# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Self-tests for the acceptance harness's own verdict logic.

They need no engine, database or browser: the SDK is replaced by a small
in-memory stand-in written to a temporary directory. They check that a harness
check cannot pass without testing anything.

Run: python3 -m unittest discover -s scripts/acceptance/graph-explorer/selftest -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
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


if __name__ == '__main__':
    unittest.main()
