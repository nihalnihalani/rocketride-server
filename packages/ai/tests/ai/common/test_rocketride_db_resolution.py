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

"""Where ``resolve_rocketride_dsn`` may take a database from, by process.

The RocketRide cloud DB nodes call it in two kinds of process: a task process,
whose environment the task engine built (``ROCKETRIDE_DB_DSNS``: the DSN of
each database it authorized and resolved for that task, or the reason there
is none), and the server process, where a node's save-time ``validateConfig``
probe runs. Neither kind ever resolves a database itself: no account call, no
identity from the environment (``ROCKETRIDE_CLIENT_ID``), no single
``ROCKETRIDE_DB_DSN``, whichever account class is loaded and whatever flags
the command line carries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import ai.account
from ai.account.base import AccountBase
from ai.common import rocketride_db

SERVER_DSN = 'postgresql://someone@pooler/some-tenant?sslmode=require'
BROKER = {'RR_DB_BROKER_URL': 'https://broker.example/provision', 'RR_DB_BROKER_TOKEN': 'token'}
# Names an older seam read: a caller's tenant and a single DSN.
LEGACY_CLIENT_ID_ENV = 'ROCKETRIDE_CLIENT_ID'
LEGACY_DSN_ENV = 'ROCKETRIDE_DB_DSN'


class _Account(AccountBase):
    """The default (broker) resolver; ``resolve_db_dsn`` is recorded per instance."""

    capabilities = ('oss',)

    async def authenticate(self, credential):  # pragma: no cover - unused
        return None


class _HostedAccount(_Account):
    capabilities = ('saas',)


class _OverlayAccount(_HostedAccount):
    """A hosted overlay that resolves DSNs itself (no broker settings needed)."""

    async def resolve_db_dsn(self, client_id, scope='org', owner_id=''):  # pragma: no cover - replaced per instance
        return SERVER_DSN


@pytest.fixture
def server_env(monkeypatch):
    """An environment that names a tenant, a single DSN and the broker, but delivers nothing."""
    for name in (*BROKER, LEGACY_DSN_ENV, LEGACY_CLIENT_ID_ENV, rocketride_db.DB_DSNS_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(rocketride_db.DB_RESOLVE_ERROR_ENV, raising=False)
    monkeypatch.setenv(LEGACY_DSN_ENV, SERVER_DSN)
    monkeypatch.setenv(LEGACY_CLIENT_ID_ENV, 'some-tenant')
    for name, value in BROKER.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _install(monkeypatch, account_cls, argv):
    """Make ``account_cls`` the loaded account and ``argv`` the command line; return the resolver calls."""
    calls = []

    async def resolver(client_id, scope='org', owner_id=''):
        calls.append(client_id)
        return SERVER_DSN

    account = account_cls()
    account.resolve_db_dsn = resolver
    monkeypatch.setattr(ai.account, 'account', account)
    monkeypatch.setattr(sys, 'argv', list(argv))
    return calls


_PROCESSES = [
    (_Account, ['engine']),
    (_Account, ['engine', '--saas']),
    (_HostedAccount, ['engine']),
    (_OverlayAccount, ['engine', '--saas']),
    (_HostedAccount, ['engine', '--hosted']),
    # Pipeline arguments can add flags to a task's command line, never remove --hosted.
    (_OverlayAccount, ['engine', '--hosted', '--saas']),
]
_PROCESS_IDS = [
    'open-source-server',
    'hosted-server-saas-flag',
    'hosted-server-saas-capability',
    'hosted-server-overlay-resolver',
    'hosted-task',
    'hosted-task-with-added-saas-flag',
]


# ---------------------------------------------------------------------------
# No process resolves a database itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('account_cls,argv', _PROCESSES, ids=_PROCESS_IDS)
def test_nothing_delivered_resolves_nothing(server_env, account_cls, argv):
    """Neither a DSN map nor a reason: refuse, without the account, the tenant or the single DSN."""
    calls = _install(server_env, account_cls, argv)

    with pytest.raises(rocketride_db.DsnNotDelivered) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert calls == []
    assert SERVER_DSN not in str(caught.value)
    assert 'some-tenant' not in str(caught.value)


@pytest.mark.parametrize('account_cls,argv', _PROCESSES, ids=_PROCESS_IDS)
def test_only_the_delivered_map_counts(server_env, account_cls, argv):
    """A delivered map is read for the node's key alone; nothing else in the environment is."""
    calls = _install(server_env, account_cls, argv)
    delivered = 'postgresql://role@pooler/org-1?sslmode=require'
    server_env.setenv(rocketride_db.DB_DSNS_ENV, json.dumps({'org': delivered}))

    assert rocketride_db.resolve_rocketride_dsn() == delivered
    with pytest.raises(ValueError, match='was not given') as caught:
        rocketride_db.resolve_rocketride_dsn('team')
    assert calls == []
    assert SERVER_DSN not in str(caught.value) and delivered not in str(caught.value)


def test_the_engines_resolve_error_is_reported(server_env):
    calls = _install(server_env, _HostedAccount, ['engine', '--hosted'])
    server_env.setenv(rocketride_db.DB_RESOLVE_ERROR_ENV, 'the org database failed to resolve: HTTP 503')

    with pytest.raises(ValueError, match='not available for this task: the org database failed to resolve'):
        rocketride_db.resolve_rocketride_dsn()
    assert calls == []


def test_resolution_does_not_import_the_account_layer(server_env):
    """The seam is stdlib only: a task process that never loaded ai.account does not load it here."""
    server_env.setattr(sys, 'argv', ['engine', '--hosted'])
    server_env.delitem(sys.modules, 'ai.account')

    with pytest.raises(rocketride_db.DsnNotDelivered):
        rocketride_db.resolve_rocketride_dsn()
    assert 'ai.account' not in sys.modules


# ---------------------------------------------------------------------------
# A hosted engine's task process, run for real
#
# A hosted engine cannot start here: --saas imports the SaaS account overlay
# (extension.saas), which this repository does not have. Everything else is
# real. Task.start_task runs as a hosted engine's does up to the launch, so
# the task's command line (with --hosted and a pipeline-added --saas) and its
# environment are the engine's own. The engine binary then starts the task
# process with them; the process runs a probe in place of the node script and
# asks for the database as a DB node does. A caller has put another tenant in
# the engine's environment (the ROCKETRIDE_* names are caller-influenced: the
# account set_env command writes them), and the --saas the pipeline added
# makes the task process load a stand-in for the overlay, which resolves a
# DSN for any tenant it is asked for.
# ---------------------------------------------------------------------------

VICTIM = 'victim-tenant'

_STAND_IN_OVERLAY = """
from ai.account.base import AccountBase


class Account(AccountBase):
    capabilities = ('saas',)

    async def authenticate(self, credential):
        return (401, 'stand-in')

    async def resolve_db_dsn(self, tenant, scope='org', owner_id=''):
        with open(@LOG@, 'a', encoding='utf-8') as f:
            f.write(tenant + '\\n')
        return 'postgresql://role@pooler/' + tenant
"""

# The engine binary does not read PYTHONPATH, so the probe puts this checkout
# and the stand-in first on sys.path itself.
_PROBE = """
import json, os, sys

sys.path[:0] = [@SRC@, @OVERLAY@]
import ai.account
from ai.common import rocketride_db

out = {
    'argv': sys.argv[1:],
    'account': type(ai.account.account).__module__,
    'module': rocketride_db.__file__,
    'client_id': os.environ.get('ROCKETRIDE_CLIENT_ID'),
}
try:
    out['dsn'] = rocketride_db.resolve_rocketride_dsn()
except Exception as e:
    out['error'] = str(e)
print('PROBE ' + json.dumps(out), flush=True)
"""


class _Launched(Exception):
    """Stops Task.start_task at the launch; the test starts the process itself."""


def _hosted_task_launch(monkeypatch, tmp_path, pipeline, pipeline_args):
    """The program, arguments, directory and environment a hosted engine starts ``pipeline``'s task with."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import tempfile

    from rocketride import TASK_STATUS

    from ai.modules.task import task_engine

    src = Path(rocketride_db.__file__).resolve().parents[2]
    overlay = tmp_path / 'overlay'
    (overlay / 'extension' / 'saas').mkdir(parents=True)
    (overlay / 'extension' / '__init__.py').write_text('')
    (overlay / 'extension' / 'saas' / '__init__.py').write_text(
        _STAND_IN_OVERLAY.replace('@LOG@', repr(str(tmp_path / 'task-resolver.log')))
    )
    probe = tmp_path / 'probe.py'
    probe.write_text(_PROBE.replace('@SRC@', repr(str(src))).replace('@OVERLAY@', repr(str(overlay))))

    # The engine's environment: a caller's tenant, a stale DSN and DSN map, the broker settings.
    monkeypatch.delenv(rocketride_db.DB_RESOLVE_ERROR_ENV, raising=False)
    monkeypatch.setenv(LEGACY_CLIENT_ID_ENV, VICTIM)
    monkeypatch.setenv(LEGACY_DSN_ENV, f'postgresql://role@pooler/{VICTIM}')
    monkeypatch.setenv(rocketride_db.DB_DSNS_ENV, json.dumps({'org': f'postgresql://role@pooler/{VICTIM}'}))
    for name, value in BROKER.items():
        monkeypatch.setenv(name, value)

    # A hosted engine (its account has the saas capability) whose resolver
    # returns a DSN for the tenant it is given.
    server_calls = []

    async def server_resolver(tenant, scope='org', owner_id=''):
        server_calls.append(tenant)
        return f'postgresql://role@pooler/{tenant}?sslmode=require'

    account = _HostedAccount()
    account.resolve_db_dsn = server_resolver
    monkeypatch.setattr(ai.account, 'account', account)

    launched = {}

    async def record_launch(program, *args, **kwargs):
        launched.update(program=program, args=list(args), cwd=kwargs['cwd'], env=kwargs['env'])
        raise _Launched()

    monkeypatch.setattr(task_engine.asyncio, 'create_subprocess_exec', record_launch)
    monkeypatch.setattr(task_engine, 'CONST_AI_NODE_SCRIPT', str(probe))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))

    task = task_engine.Task.__new__(task_engine.Task)
    task.id, task.token, task.source, task.project_id = 'task-hosted', 'tk_hosted', 'webhook_1', 'proj-hosted'
    task.client_id, task.team_id, task.org_id = 'user-1', 'team-1', 'org-1'
    task._task_name, task._pipeline, task._env = None, pipeline, {}
    task._threads, task._pipelineTraceLevel, task._run_kind, task._owner_kind = 1, None, 'dev', 'user'
    task._status, task._is_restarting = TASK_STATUS(), False
    task._server = SimpleNamespace(assign_port=lambda: 20999, _config={})
    task._launch_args = {'args': list(pipeline_args)}
    task._send_status_update = AsyncMock()
    task._terminated = AsyncMock()
    task.debug_message = MagicMock()

    with pytest.raises(_Launched):
        asyncio.run(task.start_task())
    return launched, server_calls


def _run_task_process(launch):
    """Start the task process as the engine does (stdin held open: --autoterm) and return the probe's report."""
    import json
    import subprocess
    import threading

    proc = subprocess.Popen(
        [launch['program'], *launch['args']],
        cwd=launch['cwd'],
        env=launch['env'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    timer = threading.Timer(120, proc.kill)
    timer.start()
    try:
        output = proc.stdout.read()
        proc.wait()
    finally:
        timer.cancel()
        proc.stdin.close()
    reports = [line[len('PROBE ') :] for line in output.splitlines() if line.startswith('PROBE ')]
    assert len(reports) == 1, output
    return json.loads(reports[0])


_WEBHOOK = {'id': 'webhook_1', 'provider': 'webhook', 'config': {}}


@pytest.mark.parametrize('pipeline_args', [[], ['--saas']], ids=['task-account', 'pipeline-added-saas'])
def test_a_hosted_task_process_never_resolves_a_database_the_engine_did_not(monkeypatch, tmp_path, pipeline_args):
    """No DB node, so the engine resolved nothing; code in the task process asks anyway."""
    launch, server_calls = _hosted_task_launch(monkeypatch, tmp_path, {'components': [_WEBHOOK]}, pipeline_args)

    report = _run_task_process(launch)

    assert Path(report['module']).resolve() == Path(rocketride_db.__file__).resolve(), (
        'the task process runs this checkout'
    )
    assert '--hosted' in report['argv'] and all(arg in report['argv'] for arg in pipeline_args)
    assert report['client_id'] == VICTIM, "the caller's tenant is in the task process's environment"
    if pipeline_args:
        assert report['account'] == 'extension.saas', 'the task process holds a resolver for any tenant'
    assert 'dsn' not in report, f'the task process resolved {report.get("dsn")}'
    assert report['error'].startswith('no RocketRide cloud database is delivered'), report['error']
    assert VICTIM not in report['error']
    assert not (tmp_path / 'task-resolver.log').exists(), 'the task process resolved a database itself'
    assert server_calls == []


def test_a_hosted_task_process_uses_the_database_the_engine_resolved_for_its_organization(monkeypatch, tmp_path):
    """A DB node (spelled as the engine still loads it): the task's own organization, never the caller's tenant."""
    pipeline = {'components': [_WEBHOOK, {'id': 'graph_1', 'provider': 'RocketRide_Graph', 'config': {}}]}
    launch, server_calls = _hosted_task_launch(monkeypatch, tmp_path, pipeline, ['--saas'])

    report = _run_task_process(launch)

    assert '--hosted' in report['argv'] and '--saas' in report['argv']
    assert report['account'] == 'extension.saas' and report['client_id'] == VICTIM
    assert report.get('dsn') == 'postgresql://role@pooler/org-1?sslmode=require', report
    assert server_calls == ['org-1']
    assert not (tmp_path / 'task-resolver.log').exists()
