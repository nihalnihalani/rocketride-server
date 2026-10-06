# MIT License
#
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Standalone-run shims for task-module unit tests.

The ``ai`` package's import chain reaches modules that only exist in the
assembled dist/server environment (``depends``, ``rocketlib``). Under the
builder-managed test run those are real; when running
``python -m pytest packages/ai/tests/...`` directly against the source tree
they are absent, so this conftest installs inert stand-ins BEFORE the test
modules import ``ai``. Real modules always win: stubs are only registered
when the import is unavailable.

It also provides the ``db_tasks`` fixture shared by the task-server and
task-command suites (see below).
"""

import asyncio
import itertools
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _stub_module(name: str, **attrs) -> None:
    """Register an inert module stub for ``name`` if it cannot be imported."""
    if name in sys.modules:
        return
    try:
        __import__(name)
        return
    except ImportError:
        pass
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


# dist/server dependency-bootstrap: a no-op satisfies the source tree.
_stub_module('depends', depends=lambda *_args, **_kwargs: None)

# dist/server shared logging/args helpers used by task_engine and friends.
_stub_module(
    'rocketlib',
    debug=lambda *_args, **_kwargs: None,
    args=types.SimpleNamespace(),
)


# ---------------------------------------------------------------------------
# db_tasks: the tenant a task's RocketRide database nodes get, end to end
# ---------------------------------------------------------------------------

# Every place a caller could try to name another tenant: pipeline fields,
# node configs and request arguments...
TENANT_SPOOF = {
    'tenant_id': 'victim-org',
    'org_id': 'victim-org',
    'orgId': 'victim-org',
    'client_id': 'victim-user',
    'clientId': 'victim-user',
    'dsn': 'postgresql://victim@pooler/victim-org',
}

# ...and ROCKETRIDE_* names in the engine's environment, the secret layers and
# a request's env.
TENANT_SPOOF_ENV = {
    'ROCKETRIDE_CLIENT_ID': 'victim-user',
    'ROCKETRIDE_ORG_ID': 'victim-org',
    'ROCKETRIDE_TEAM_ID': 'victim-team',
    'ROCKETRIDE_TENANT_ID': 'victim-org',
    'ROCKETRIDE_DB_DSN': 'postgresql://victim@pooler/victim-org',
}


def _spoofing_db_pipeline():
    """A pipeline with RocketRide graph and SQL nodes whose fields and configs name another tenant."""
    return {
        **TENANT_SPOOF,
        'project_id': 'project-1',
        'source': 'src',
        'components': [
            {'id': 'src', 'provider': 'webhook', 'config': dict(TENANT_SPOOF)},
            {'id': 'graph', 'provider': 'rocketride_graph', 'config': dict(TENANT_SPOOF)},
            {'id': 'sql', 'provider': 'rocketride_sql', 'config': {'db': dict(TENANT_SPOOF)}},
        ],
    }


@pytest.fixture
def db_tasks(monkeypatch):
    """A real TaskServer whose real Tasks record their tenant instead of starting a process.

    ``TaskServer.start_task`` runs unchanged and builds the real ``Task``; the
    Task's start records the environment its process would get
    (``Task._build_subprocess_env``, where the database DSN is resolved).
    Every name in TENANT_SPOOF_ENV is set in the engine's environment and
    returned by the account's secret merge.

    Returns a namespace: ``server``, ``tenants`` (each tenant id passed to
    ``resolve_db_dsn``, in call order), ``envs`` (task token -> its process
    environment), ``pipeline()`` (a fresh spoofing DB pipeline), ``spoof``
    and ``spoof_env``.
    """
    from ai.account import account as account_singleton
    from ai.modules.task.task_engine import Task
    from ai.modules.task.task_server import TaskServer

    ts = TaskServer.__new__(TaskServer)
    ts._task_control = {}
    ts._connections = {}
    ts._connection_id = 0
    ts._unauthed_by_ip = {}
    ts._allocated_ports = []
    ts._reserved_ports = set()
    ts._store_instance = None
    ts._config = {}
    ts._server = MagicMock()
    serial = itertools.count(1)
    ts._server.account.generate_token.side_effect = lambda content, prefix='': f'{prefix}{next(serial):032x}'
    ts.debug_message = MagicMock()

    tenants = []
    envs = {}

    async def resolve_db_dsn(tenant_id):
        tenants.append(tenant_id)
        # Yield, unevenly, so concurrent task starts interleave inside resolution.
        await asyncio.sleep(0.01 if tenant_id.endswith('a') else 0)
        return f'postgresql://role@pooler/{tenant_id}'

    async def record_start(task):
        envs[task.token] = await task._build_subprocess_env()

    monkeypatch.setattr(account_singleton, 'resolve_db_dsn', resolve_db_dsn)
    monkeypatch.setattr(account_singleton, 'get_merged_env', AsyncMock(return_value=dict(TENANT_SPOOF_ENV)))
    monkeypatch.setattr(Task, 'start_task', record_start)
    monkeypatch.setattr(Task, 'wait_for_running', AsyncMock())
    for name, value in TENANT_SPOOF_ENV.items():
        monkeypatch.setenv(name, value)
    return types.SimpleNamespace(
        server=ts,
        tenants=tenants,
        envs=envs,
        pipeline=_spoofing_db_pipeline,
        spoof=dict(TENANT_SPOOF),
        spoof_env=dict(TENANT_SPOOF_ENV),
    )
