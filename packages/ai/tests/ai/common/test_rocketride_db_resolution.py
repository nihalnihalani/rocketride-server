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

import pytest

import ai.account
from ai.account.base import AccountBase
from ai.common import rocketride_db

SERVER_DSN = 'postgresql://someone@pooler/some-tenant?sslmode=require'
BROKER = {'RR_DB_BROKER_URL': 'https://broker.example/provision', 'RR_DB_BROKER_TOKEN': 'token'}
UNCONFIGURED = 'the RocketRide cloud database broker is not configured on this server'


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
