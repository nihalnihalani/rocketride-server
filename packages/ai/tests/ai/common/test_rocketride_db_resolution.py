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
whose environment the task engine built (the DSN it resolved for that task, or
the reason there is none), and the server process, where a node's save-time
``validateConfig`` probe runs. A hosted engine's server process serves every
tenant and the probe carries no tenant, so there it must never take a DSN or an
identity from the server's own environment: it reports the broker state instead.
The open-source server process (one tenant, ``ROCKETRIDE_DB_DSN`` set for local
development) keeps resolving from its environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import ai.account
from ai.account.base import AccountBase
from ai.common import rocketride_db

SERVER_DSN = 'postgresql://someone@pooler/some-tenant?sslmode=require'
BROKER = {'RR_DB_BROKER_URL': 'https://broker.example/provision', 'RR_DB_BROKER_TOKEN': 'token'}
UNCONFIGURED = 'the RocketRide cloud database broker is not configured on this server'
# rocketride_db.NOT_RESOLVED, spelled out so a run against older code fails on the behaviour.
NOT_RESOLVED_TEXT = 'the task engine resolved no database for this task'


class _Account(AccountBase):
    """The default (broker) resolver; ``resolve_db_dsn`` is recorded per instance."""

    capabilities = ('oss',)

    async def authenticate(self, credential):  # pragma: no cover - unused
        return None


class _HostedAccount(_Account):
    capabilities = ('saas',)


class _OverlayAccount(_HostedAccount):
    """A hosted overlay that resolves DSNs itself (no broker settings needed)."""

    async def resolve_db_dsn(self, client_id):  # pragma: no cover - replaced per instance
        return SERVER_DSN


@pytest.fixture
def server_env(monkeypatch):
    """A server environment that names a DSN, an identity and a stale error."""
    for name in (*BROKER, rocketride_db.DB_DSN_ENV, rocketride_db.CLIENT_ID_ENV, rocketride_db.DB_RESOLVE_ERROR_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(rocketride_db.DB_DSN_ENV, SERVER_DSN)
    monkeypatch.setenv(rocketride_db.CLIENT_ID_ENV, 'some-tenant')
    return monkeypatch


def _install(monkeypatch, account_cls, argv):
    """Make ``account_cls`` the loaded account and ``argv`` the command line; return the resolver calls."""
    calls = []

    async def resolver(client_id):
        calls.append(client_id)
        return SERVER_DSN

    account = account_cls()
    account.resolve_db_dsn = resolver
    monkeypatch.setattr(ai.account, 'account', account)
    monkeypatch.setattr(sys, 'argv', list(argv))
    return calls


# ---------------------------------------------------------------------------
# A hosted engine's server process resolves no tenant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'account_cls,argv',
    [
        (_Account, ['engine', '--saas']),  # the engine's own launch flag
        (_HostedAccount, ['engine']),  # the account's saas capability
    ],
    ids=['saas-flag', 'saas-capability'],
)
def test_hosted_server_never_uses_its_own_dsn_or_identity(server_env, account_cls, argv):
    calls = _install(server_env, account_cls, argv)

    with pytest.raises(ValueError) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert calls == []
    assert SERVER_DSN not in str(caught.value)
    assert 'some-tenant' not in str(caught.value)


def test_hosted_server_without_broker_reports_the_task_start_wording(server_env):
    _install(server_env, _HostedAccount, ['engine', '--saas'])

    with pytest.raises(ValueError, match=UNCONFIGURED):
        rocketride_db.resolve_rocketride_dsn()


def test_hosted_server_without_identity_reports_the_broker_not_the_identity(monkeypatch):
    """The misleading 'ROCKETRIDE_CLIENT_ID is not set' message is gone."""
    for name in (*BROKER, rocketride_db.DB_DSN_ENV, rocketride_db.CLIENT_ID_ENV, rocketride_db.DB_RESOLVE_ERROR_ENV):
        monkeypatch.delenv(name, raising=False)
    _install(monkeypatch, _HostedAccount, ['engine', '--saas'])

    with pytest.raises(ValueError) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert UNCONFIGURED in str(caught.value)
    assert rocketride_db.CLIENT_ID_ENV not in str(caught.value)


def test_hosted_server_ignores_a_resolve_error_in_its_own_environment(server_env):
    """ROCKETRIDE_DB_RESOLVE_ERROR is the engine's message to a task, not server state."""
    server_env.setenv(rocketride_db.DB_RESOLVE_ERROR_ENV, 'stale reason from somewhere')
    _install(server_env, _HostedAccount, ['engine', '--saas'])

    with pytest.raises(ValueError) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert UNCONFIGURED in str(caught.value)
    assert 'stale reason' not in str(caught.value)


@pytest.mark.parametrize('account_cls', [_HostedAccount, _OverlayAccount], ids=['broker', 'overlay-resolver'])
def test_hosted_server_with_a_resolver_defers_to_task_start(server_env, account_cls):
    """Broker configured (or an overlay resolving DSNs itself): nothing to check before a task starts."""
    for name, value in BROKER.items():
        server_env.setenv(name, value)
    calls = _install(server_env, account_cls, ['engine', '--saas'])

    with pytest.raises(rocketride_db.ResolvedAtTaskStart) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert calls == []
    assert 'when a task starts' in str(caught.value)
    assert 'not configured' not in str(caught.value)


def test_overlay_resolver_counts_as_configured_without_broker_settings(server_env):
    calls = _install(server_env, _OverlayAccount, ['engine', '--saas'])

    with pytest.raises(rocketride_db.ResolvedAtTaskStart):
        rocketride_db.resolve_rocketride_dsn()

    assert calls == []


def test_broker_wording_matches_the_task_engine():
    """The probe and a task-start failure say the same thing."""
    from ai.modules.task import task_engine

    assert rocketride_db.BROKER_UNCONFIGURED == task_engine.CONST_DB_BROKER_UNCONFIGURED
    assert rocketride_db.HOSTED_CHILD_FLAG == task_engine.CONST_HOSTED_CHILD_FLAG


# ---------------------------------------------------------------------------
# Task processes and the open-source server keep resolving as before
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'argv',
    [
        ['engine', '--hosted'],
        # Pipeline arguments can add flags to a task's command line, never
        # remove --hosted: an added --saas does not make a task the server.
        ['engine', '--hosted', '--saas'],
    ],
    ids=['hosted-task', 'hosted-task-with-added-saas-flag'],
)
def test_hosted_task_process_uses_the_dsn_the_engine_injected(server_env, argv):
    calls = _install(server_env, _HostedAccount, argv)

    assert rocketride_db.resolve_rocketride_dsn() == SERVER_DSN
    assert calls == []


def test_hosted_task_process_reports_the_engine_resolve_error(server_env):
    server_env.delenv(rocketride_db.DB_DSN_ENV)
    server_env.setenv(rocketride_db.DB_RESOLVE_ERROR_ENV, UNCONFIGURED)
    _install(server_env, _Account, ['engine', '--hosted'])

    with pytest.raises(ValueError, match='at task start: ' + UNCONFIGURED):
        rocketride_db.resolve_rocketride_dsn()


@pytest.mark.parametrize('injected', [None, '   '], ids=['no-dsn', 'blank-dsn'])
@pytest.mark.parametrize(
    'argv',
    [['engine', '--hosted'], ['engine', '--hosted', '--saas']],
    ids=['hosted-task', 'hosted-task-with-added-saas-flag'],
)
@pytest.mark.parametrize(
    'account_cls', [_Account, _HostedAccount, _OverlayAccount], ids=['base', 'hosted', 'overlay-resolver']
)
def test_hosted_task_process_without_a_resolved_database_never_resolves_one_itself(
    server_env, account_cls, argv, injected
):
    """Neither a DSN nor a reason from the task engine: say so, and resolve nothing here.

    The account fallback would take the tenant from the task's own environment
    (ROCKETRIDE_CLIENT_ID) through whichever account class the task loaded, and
    pipeline code and pipeline-added arguments (``--saas``) reach both.
    """
    server_env.delenv(rocketride_db.DB_DSN_ENV)
    if injected is not None:
        server_env.setenv(rocketride_db.DB_DSN_ENV, injected)
    calls = _install(server_env, account_cls, argv)

    with pytest.raises(ValueError) as caught:
        rocketride_db.resolve_rocketride_dsn()

    assert calls == []
    message = str(caught.value)
    assert 'at task start' in message and rocketride_db.NOT_RESOLVED in message
    assert 'some-tenant' not in message and rocketride_db.CLIENT_ID_ENV not in message


def test_open_source_server_uses_its_own_dsn(server_env):
    """Single-tenant local development: ROCKETRIDE_DB_DSN in the engine's environment."""
    calls = _install(server_env, _Account, ['engine'])

    assert rocketride_db.resolve_rocketride_dsn() == SERVER_DSN
    assert calls == []


def test_open_source_server_falls_back_to_the_account(server_env):
    server_env.delenv(rocketride_db.DB_DSN_ENV)
    calls = _install(server_env, _Account, ['engine'])

    assert rocketride_db.resolve_rocketride_dsn() == SERVER_DSN
    assert calls == ['some-tenant']


def test_hosted_detection_does_not_import_the_account_layer(server_env):
    """A task process or an isolated test that never loaded ai.account is not hosted."""
    server_env.setattr(sys, 'argv', ['engine'])
    server_env.delitem(sys.modules, 'ai.account')

    assert rocketride_db.resolve_rocketride_dsn() == SERVER_DSN
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

    async def resolve_db_dsn(self, tenant):
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

    # The engine's environment: a caller's tenant, a stale DSN, the broker settings.
    for name in (rocketride_db.DB_DSN_ENV, rocketride_db.DB_RESOLVE_ERROR_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(rocketride_db.CLIENT_ID_ENV, VICTIM)
    monkeypatch.setenv(rocketride_db.DB_DSN_ENV, f'postgresql://role@pooler/{VICTIM}')
    for name, value in BROKER.items():
        monkeypatch.setenv(name, value)

    # A hosted engine (its account has the saas capability) whose resolver
    # returns a DSN for the tenant it is given.
    server_calls = []

    async def server_resolver(tenant):
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
    assert report['error'] == f'RocketRide cloud database resolution failed at task start: {NOT_RESOLVED_TEXT}'
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
