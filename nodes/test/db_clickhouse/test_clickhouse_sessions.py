# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""The ClickHouse node tells agents its sessions are not transactions.

clickhouse-sqlalchemy's native connector makes ``commit`` and ``rollback``
no-ops and ClickHouse has no savepoints, so ``IInstance`` overrides the shared
``_sessionsAreTransactions`` hook. The shared tool descriptions and errors read
it; their wording is covered by ``packages/ai/tests/database/test_execute_session.py``.
This pins that the real node opts out, so an agent reading the ClickHouse
tools is never told its work can be rolled back.
"""

import contextlib
import importlib
import sys
import types
from pathlib import Path

import pytest

from ai.common.database import DatabaseInstanceBase

NODES_DIR = Path(__file__).resolve().parents[2] / 'src' / 'nodes'


@contextlib.contextmanager
def _loaded_iinstance(node):
    """Load ``nodes/src/nodes/<node>/IInstance.py`` without running the package ``__init__``.

    The ``__init__`` calls ``depends()``, which installs the node's driver
    requirements; these tests need none of them. A bare package module with the
    node directory as its path lets ``IInstance``'s relative import of
    ``IGlobal`` resolve, and ``sys.modules`` is restored afterwards.
    """
    names = (node, f'{node}.IGlobal', f'{node}.IInstance')
    saved = {name: sys.modules.get(name) for name in names}
    package = types.ModuleType(node)
    package.__path__ = [str(NODES_DIR / node)]
    sys.modules[node] = package
    try:
        yield importlib.import_module(f'{node}.IInstance').IInstance
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.fixture(scope='module')
def IInstance():
    """The db_clickhouse node's ``IInstance`` class."""
    with _loaded_iinstance('db_clickhouse') as cls:
        yield cls


def _describe(inst, name):
    """The description an agent reads for one of the node's tools."""
    return getattr(DatabaseInstanceBase, name).__tool_meta__['description'](inst)


def test_clickhouse_sessions_are_not_transactions(IInstance):
    """The node overrides the hook the shared descriptions read."""
    inst = IInstance.__new__(IInstance)

    assert inst._sessionsAreTransactions() is False


def test_clickhouse_tools_promise_no_rollback(IInstance):
    """``execute``, ``begin``, ``commit`` and ``rollback`` all say what a session really is."""
    inst = IInstance.__new__(IInstance)

    assert 'A session on ClickHouse opens no transaction' in _describe(inst, 'execute')
    assert 'rollback to savepoint' not in _describe(inst, 'execute')
    assert _describe(inst, 'begin').startswith('Reserve a connection on this ClickHouse database')
    assert _describe(inst, 'commit').startswith('Close a session.')
    assert _describe(inst, 'rollback').startswith('Close a session. This undoes nothing')


@pytest.mark.parametrize('node', ['db_mysql', 'db_postgres', 'rocketride_sql'])
def test_the_other_sql_nodes_keep_transactional_sessions(node):
    """Only db_clickhouse opts out; every other SQL node's session is a real transaction.

    Their READMEs and tool descriptions tell an agent that ``rollback`` discards
    the session's work and that ``rollback to savepoint`` recovers a failed
    statement. That is true only while the node leaves ``_sessionsAreTransactions``
    at the base default, so an override copied over from db_clickhouse would
    silently turn those promises into ClickHouse's "this undoes nothing".
    """
    with _loaded_iinstance(node) as cls:
        inst = cls.__new__(cls)

        assert inst._sessionsAreTransactions() is True
        execute = _describe(inst, 'execute')
        assert 'rollback to savepoint' in execute
        assert 'opens no transaction' not in execute
        assert _describe(inst, 'rollback').startswith('Roll back')
