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

"""Tests for begin/commit/rollback tool functions and session-aware execute."""

import types

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from ai.common.database.db_global_base import DatabaseGlobalBase
from ai.common.database.db_instance_base import DatabaseInstanceBase
from ai.common.database.tx_registry import TransactionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_shared():
    """In-memory SQLite engine with a shared StaticPool connection (like test_tx_registry)."""
    e = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with e.begin() as c:
        c.execute(text('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)'))
    return e


def _make_iglobal(*, allow_execute: bool, engine=None):
    """Build a minimal IGlobal stub with a real TransactionRegistry."""
    if engine is None:
        engine = _engine_shared()
    registry = TransactionRegistry(engine, max_rows=1000)
    iglobal = types.SimpleNamespace(
        allow_execute=allow_execute,
        max_execute_rows=1000,
        engine=engine,
        tx_registry=registry,
    )
    # A failed stateless execute formats the driver error through IGlobal, so
    # the stub borrows the real implementation. Without it the failure path
    # dies with AttributeError instead of raising the RuntimeError under test.
    iglobal._format_db_error = types.MethodType(DatabaseGlobalBase._format_db_error, iglobal)
    return iglobal


def _make_instance(iglobal):
    """Instantiate a concrete DatabaseInstanceBase subclass with the given IGlobal."""

    class _Concrete(DatabaseInstanceBase):
        def _db_display_name(self):
            return 'TestDB'

        def _db_dialect(self):
            return 'sqlite'

    inst = _Concrete.__new__(_Concrete)
    inst.IGlobal = iglobal
    return inst


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def instance_with_execute_disabled():
    iglobal = _make_iglobal(allow_execute=False)
    return _make_instance(iglobal)


@pytest.fixture
def instance_with_sqlite_registry():
    iglobal = _make_iglobal(allow_execute=True)
    return _make_instance(iglobal)


# ---------------------------------------------------------------------------
# (a) Gate enforcement: all tx tools refuse when allow_execute=False
# ---------------------------------------------------------------------------


def test_begin_requires_allow_execute(instance_with_execute_disabled):
    with pytest.raises(ValueError, match='allow_execute'):
        instance_with_execute_disabled.begin({})


def test_commit_requires_allow_execute(instance_with_execute_disabled):
    with pytest.raises(ValueError, match='allow_execute'):
        instance_with_execute_disabled.commit({'session_id': 'fake'})


def test_rollback_requires_allow_execute(instance_with_execute_disabled):
    with pytest.raises(ValueError, match='allow_execute'):
        instance_with_execute_disabled.rollback({'session_id': 'fake'})


def test_execute_with_session_id_requires_allow_execute(instance_with_execute_disabled):
    with pytest.raises(ValueError, match='allow_execute'):
        instance_with_execute_disabled.execute({'sql': 'SELECT 1', 'session_id': 'fake'})


# ---------------------------------------------------------------------------
# (b) Full roundtrip: begin → execute(INSERT with params) → commit → stateless SELECT
# ---------------------------------------------------------------------------


def test_session_roundtrip(instance_with_sqlite_registry):
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']
    inst.execute({'sql': 'INSERT INTO t (v) VALUES ($1)', 'params': ['z'], 'session_id': sid})
    inst.commit({'session_id': sid})
    out = inst.execute({'sql': 'SELECT v FROM t'})
    assert out['rows'] == [{'v': 'z'}]


def test_begin_returns_session_id(instance_with_sqlite_registry):
    result = instance_with_sqlite_registry.begin({})
    assert 'session_id' in result
    assert isinstance(result['session_id'], str)
    assert len(result['session_id']) > 0


def test_commit_returns_ok(instance_with_sqlite_registry):
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']
    result = inst.commit({'session_id': sid})
    assert result == {'ok': True}


# ---------------------------------------------------------------------------
# (c) Rollback discards uncommitted rows
# ---------------------------------------------------------------------------


def test_rollback_discards_row(instance_with_sqlite_registry):
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']
    inst.execute({'sql': 'INSERT INTO t (v) VALUES ($1)', 'params': ['should_vanish'], 'session_id': sid})
    result = inst.rollback({'session_id': sid})
    assert result == {'ok': True}
    # Stateless read should see no rows
    out = inst.execute({'sql': 'SELECT v FROM t'})
    assert out['rows'] == []
    # The session is invalidated after rollback: reusing the sid must error
    # (mirrors the post-reap invalidation in test_reap_idle_rolls_back).
    with pytest.raises(ValueError):
        inst.execute({'sql': 'SELECT 1', 'session_id': sid})
    with pytest.raises(ValueError):
        inst.commit({'session_id': sid})


def test_stateless_execute_overflow_rolls_back_write(instance_with_sqlite_registry):
    """A non-session write whose RETURNING overflows max_execute_rows must roll back.

    Regression: _executeRawQuery used to log + return None inside engine.begin(),
    so the write committed even though execute() raised.
    """
    inst = instance_with_sqlite_registry
    inst.IGlobal.max_execute_rows = 0  # any RETURNING row overflows
    with pytest.raises(RuntimeError, match='max_execute_rows'):
        inst.execute({'sql': "INSERT INTO t (v) VALUES ('rollback_me') RETURNING v"})
    # The overflowing write must NOT have persisted.
    inst.IGlobal.max_execute_rows = 1000
    out = inst.execute({'sql': 'SELECT v FROM t'})
    assert out['rows'] == []


def test_session_execute_overflow_releases_session(instance_with_sqlite_registry):
    """A session-bound execute that overflows rolls back and releases the session.

    Otherwise the held connection stays pinned until idle-reaping and the aborted
    statement remains committable.
    """
    inst = instance_with_sqlite_registry
    # 0-row cap so a session RETURNING overflows.
    inst.IGlobal.tx_registry = TransactionRegistry(inst.IGlobal.engine, max_rows=0)
    sid = inst.begin({})['session_id']
    with pytest.raises(RuntimeError, match='max_rows'):
        inst.execute({'sql': "INSERT INTO t (v) VALUES ('x') RETURNING v", 'session_id': sid})
    # The session was rolled back and released: reusing it now errors.
    with pytest.raises(ValueError, match='unknown or expired'):
        inst.commit({'session_id': sid})


# ---------------------------------------------------------------------------
# (d) execute with unknown session_id raises ValueError
# ---------------------------------------------------------------------------


def test_stateless_execute_surfaces_the_driver_error(instance_with_sqlite_registry):
    """A bad statement outside a session raises with the database's own message.

    Also pins the fixture: execute()'s failure path calls IGlobal._format_db_error,
    so an IGlobal stub without it fails with AttributeError instead. The tail
    assertions are the load-bearing half: a test that only matched the
    'SQL execution failed: ' prefix would also pass against a message that
    still carried the statement, because the driver text comes first.
    """
    with pytest.raises(RuntimeError) as excinfo:
        instance_with_sqlite_registry.execute(
            {'sql': 'SELECT * FROM no_such_table WHERE v = $1', 'params': ['ada@example.com']}
        )

    message = str(excinfo.value)
    assert message.startswith('SQL execution failed: ')
    assert 'no_such_table' in message
    assert 'ada@example.com' not in message
    assert '[SQL:' not in message
    assert '[parameters:' not in message
    assert 'sqlalche.me' not in message


def test_session_execute_surfaces_the_driver_error(instance_with_sqlite_registry):
    """The session-bound half of execute owes the caller the same contract.

    ``TransactionRegistry.execute`` has no try/except, so before this fix the
    raw SQLAlchemy exception reached the caller of the same tool, behind the
    same allow_execute gate, with the ``[SQL: ...]`` / ``[parameters: ...]``
    tail the sessionless half strips.
    """
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']

    with pytest.raises(RuntimeError) as excinfo:
        inst.execute({'sql': 'SELECT * FROM no_such_table', 'session_id': sid})

    message = str(excinfo.value)
    assert message.startswith('SQL execution failed: ')
    assert 'no_such_table' in message
    assert '[SQL:' not in message
    assert '[parameters:' not in message
    assert 'sqlalche.me' not in message


def test_session_execute_error_does_not_echo_bound_parameters(instance_with_sqlite_registry):
    """A value the caller bound must not come back inside the error message."""
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']

    with pytest.raises(RuntimeError) as excinfo:
        inst.execute(
            {'sql': 'SELECT * FROM no_such_table WHERE v = $1', 'params': ['ada@example.com'], 'session_id': sid}
        )

    message = str(excinfo.value)
    assert message.startswith('SQL execution failed: ')
    assert 'ada@example.com' not in message
    assert '[parameters:' not in message


def test_session_execute_failure_releases_the_session(instance_with_sqlite_registry):
    """The failed session is rolled back and released, not left pinned.

    Same guarantee the max-rows path already had: the held connection goes
    back to the pool and the aborted statement is no longer committable.
    """
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']

    with pytest.raises(RuntimeError, match='SQL execution failed: '):
        inst.execute({'sql': 'SELECT * FROM no_such_table', 'session_id': sid})

    with pytest.raises(ValueError, match='unknown or expired'):
        inst.commit({'session_id': sid})


def test_session_execute_cleanup_failure_does_not_mask_the_driver_error(instance_with_sqlite_registry):
    """A rollback that itself fails must not replace the error being reported.

    The caller asked why their statement failed; a secondary failure while
    releasing the session is a server-side concern and belongs in the log.
    """
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']

    def _boom(_session_id):
        raise RuntimeError('boom')

    inst.IGlobal.tx_registry.rollback = _boom

    with pytest.raises(RuntimeError) as excinfo:
        inst.execute({'sql': 'SELECT * FROM no_such_table', 'session_id': sid})

    message = str(excinfo.value)
    assert message.startswith('SQL execution failed: ')
    assert 'no_such_table' in message
    assert 'boom' not in message


def test_session_execute_returns_rows_on_success(instance_with_sqlite_registry):
    """The success path through the session is unchanged by the error arm."""
    inst = instance_with_sqlite_registry
    sid = inst.begin({})['session_id']
    assert inst.execute({'sql': 'SELECT 1 AS one', 'session_id': sid}) == {'rows': [{'one': 1}], 'affected_rows': 0}
    inst.rollback({'session_id': sid})


def test_execute_unknown_session_id_raises_value_error(instance_with_sqlite_registry):
    with pytest.raises(ValueError, match='unknown or expired transaction session'):
        instance_with_sqlite_registry.execute({'sql': 'SELECT 1', 'session_id': 'no-such-session'})


def test_commit_unknown_session_id_raises_value_error(instance_with_sqlite_registry):
    with pytest.raises(ValueError, match='unknown or expired transaction session'):
        instance_with_sqlite_registry.commit({'session_id': 'no-such-session'})


def test_rollback_unknown_session_id_raises_value_error(instance_with_sqlite_registry):
    with pytest.raises(ValueError, match='unknown or expired transaction session'):
        instance_with_sqlite_registry.rollback({'session_id': 'no-such-session'})
