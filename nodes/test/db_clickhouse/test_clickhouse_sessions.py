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

import sys
from pathlib import Path

NODES_SRC = Path(__file__).parent.parent.parent / 'src' / 'nodes'
# Move to the front rather than "insert only if absent": another test dir already on
# sys.path can hold a package with the same name as the node (see #1687).
while str(NODES_SRC) in sys.path:
    sys.path.remove(str(NODES_SRC))
sys.path.insert(0, str(NODES_SRC))

from ai.common.database import DatabaseInstanceBase  # noqa: E402
from db_clickhouse.IInstance import IInstance  # noqa: E402


def _describe(inst, name):
    """The description an agent reads for one of the node's tools."""
    return getattr(DatabaseInstanceBase, name).__tool_meta__['description'](inst)


def test_clickhouse_sessions_are_not_transactions():
    """The node overrides the hook the shared descriptions read."""
    inst = IInstance.__new__(IInstance)

    assert inst._sessionsAreTransactions() is False


def test_clickhouse_tools_promise_no_rollback():
    """``execute``, ``begin``, ``commit`` and ``rollback`` all say what a session really is."""
    inst = IInstance.__new__(IInstance)

    assert 'A session on ClickHouse opens no transaction' in _describe(inst, 'execute')
    assert 'rollback to savepoint' not in _describe(inst, 'execute')
    assert _describe(inst, 'begin').startswith('Reserve a connection on this ClickHouse database')
    assert _describe(inst, 'commit').startswith('Close a session.')
    assert _describe(inst, 'rollback').startswith('Close a session. This undoes nothing')
