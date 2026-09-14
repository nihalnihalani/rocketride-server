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

"""Tests for execute()'s error reporting and the refresh_schema tool.

Both cover ``DatabaseInstanceBase`` behaviour that only shows up against a
real engine, so every test here runs on the in-memory SQLite engine the
fixtures build. Deliberately a separate module from ``test_db_base.py``: that
file is being appended to by more than one open pull request.

Covered:

- ``execute`` surfaces the driver's own message instead of a generic string.
- ``refresh_schema`` re-reflects the database, so DDL run after task start
  becomes visible (``get_schema`` keeps serving the start-up snapshot).
"""

from __future__ import annotations

import re
import threading

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from ai.common.database.db_global_base import DatabaseGlobalBase
from ai.common.database.db_instance_base import DatabaseInstanceBase


# ---------------------------------------------------------------------------
# Concrete subclasses satisfying the two ABCs
# ---------------------------------------------------------------------------


class _TestableGlobal(DatabaseGlobalBase):
    """Concrete DatabaseGlobalBase that knows how to build a SQLite URL."""

    def _connection_params(self, config):
        """Trivial mapping — every key passes through."""
        return dict(config)

    def _build_connection_url(self, params):
        """Build a sqlite:///:memory: URL (params ignored)."""
        return 'sqlite:///:memory:'


class _TestableInstance(DatabaseInstanceBase):
    """Concrete DatabaseInstanceBase that satisfies the two abstract methods."""

    def _db_display_name(self):
        """Human-readable name used in tool descriptions."""
        return 'TestDB'

    def _db_dialect(self):
        """Machine-readable dialect identifier."""
        return 'testdb'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_instance(engine):
    """Build an instance over the given engine, as beginGlobal would leave it.

    The global is a genuine DatabaseGlobalBase subclass, so ``_format_db_error``
    and ``_getDatabaseSchema`` are the production implementations; only the
    fields ``beginGlobal`` sets are filled in by hand. ``db_schema`` starts
    empty, which is exactly what task start leaves behind for a database that
    was empty at the time.
    """
    iglobal = _TestableGlobal.__new__(_TestableGlobal)
    iglobal.engine = engine
    iglobal.schema = {}
    iglobal.db_schema = {}
    iglobal.database = 'main'
    iglobal.allow_execute = True
    iglobal.max_execute_rows = 1000

    inst = _TestableInstance.__new__(_TestableInstance)
    inst.IGlobal = iglobal
    return inst


@pytest.fixture
def instance():
    """Single-threaded instance on an in-memory SQLite database.

    The default pool reuses one connection per thread, so DDL run through
    execute() is visible to the inspector afterwards.
    """
    inst = _make_instance(create_engine('sqlite:///:memory:'))
    yield inst
    inst.IGlobal.engine.dispose()


@pytest.fixture
def shared_instance():
    """Instance whose in-memory database is shared across threads.

    ``sqlite:///:memory:`` normally hands every thread its own empty database,
    which would make a concurrency test assert nothing. StaticPool plus
    ``check_same_thread`` pins all threads to one connection (the same shape
    tests/database/test_execute_session.py uses).
    """
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    inst = _make_instance(engine)
    yield inst
    engine.dispose()


# ---------------------------------------------------------------------------
# execute() error text
# ---------------------------------------------------------------------------


def test_execute_raises_with_the_driver_error_text(instance):
    """A failed statement must carry the database's own message to the caller.

    Before this fix _executeRawQuery logged the SQLAlchemyError and returned
    None, so every failure reached the caller as the same opaque 'check server
    logs for details' string: a typo, a missing table, and a permission error
    were indistinguishable in any UI built on the tool.
    """
    with pytest.raises(RuntimeError) as excinfo:
        instance.execute({'sql': 'SELECT * FROM no_such_table'})

    message = str(excinfo.value)
    assert message.startswith('SQL execution failed: ')
    assert 'no_such_table' in message
    assert 'no such table' in message.lower()


def test_execute_error_names_the_offending_column(instance):
    """The message is specific enough to locate the mistake, not just its kind."""
    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY)'})

    with pytest.raises(RuntimeError, match='no_such_column'):
        instance.execute({'sql': 'SELECT no_such_column FROM widgets'})


def test_execute_error_does_not_mention_server_logs(instance):
    """The old message pointed at the server log; the new one answers directly."""
    with pytest.raises(RuntimeError) as excinfo:
        instance.execute({'sql': 'THIS IS NOT SQL'})

    assert 'check server logs' not in str(excinfo.value)


def test_execute_returns_rows_on_success(instance):
    """The success path is unchanged by the error-handling rewrite."""
    assert instance.execute({'sql': 'SELECT 1 AS one'}) == {'rows': [{'one': 1}], 'affected_rows': 0}


def test_execute_still_refuses_when_the_gate_is_off(instance):
    """The allow_execute gate runs before any of this and is untouched."""
    instance.IGlobal.allow_execute = False
    with pytest.raises(ValueError, match='allow_execute'):
        instance.execute({'sql': 'SELECT 1'})


# ---------------------------------------------------------------------------
# refresh_schema
# ---------------------------------------------------------------------------


def test_refresh_schema_sees_a_table_created_after_startup(instance):
    """refresh_schema must re-reflect, not re-serve the task-start snapshot.

    db_schema is assigned exactly once, in beginGlobal. Without a refresh tool
    a table created through execute stays invisible to get_schema for the whole
    life of the task, so a designer that applies DDL and re-reads the schema
    repaints the pre-DDL shape.
    """
    # The task-start snapshot: empty, as beginGlobal would have left it.
    assert instance.get_schema({}) == {'database': 'main', 'tables': {}}

    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT)'})

    # get_schema still serves the stale snapshot ...
    assert instance.get_schema({})['tables'] == {}

    # ... refresh_schema reflects the live database.
    refreshed = instance.refresh_schema({})
    assert refreshed['database'] == 'main'
    assert [c['column'] for c in refreshed['tables']['widgets']['columns']] == ['id', 'label']
    assert refreshed['tables']['widgets']['primary_key'] == ['id']

    # The cache was replaced, so get_schema now agrees with it.
    assert instance.get_schema({'table': 'widgets'})['tables']['widgets'] == refreshed['tables']['widgets']


def test_refresh_schema_reports_a_utc_timestamp(instance):
    """refreshed_at lets a caller show how current the schema it is holding is."""
    refreshed_at = instance.refresh_schema({})['refreshed_at']
    # ISO-8601 with an explicit UTC offset, e.g. 2026-09-14T20:31:07.123456+00:00.
    assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$', refreshed_at)


def test_refresh_schema_matches_get_schema_shape(instance):
    """Apart from refreshed_at, the two tools return the same payload."""
    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY)'})
    refreshed = instance.refresh_schema({})

    assert refreshed.pop('refreshed_at')
    assert refreshed == instance.get_schema({})


def test_refresh_schema_ignores_its_input(instance):
    """The tool declares no input; anything passed is ignored rather than fatal."""
    for args in (None, {}, {'unexpected': 1}):
        assert 'tables' in instance.refresh_schema(args)


def test_refresh_schema_drops_a_table_that_no_longer_exists(instance):
    """Re-reflection REPLACES the cache; it does not merge into it."""
    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY)'})
    assert 'widgets' in instance.refresh_schema({})['tables']

    instance.execute({'sql': 'DROP TABLE widgets'})
    assert instance.refresh_schema({})['tables'] == {}


def test_concurrent_refresh_schema_calls_all_succeed(shared_instance):
    """The lock serialises reflection without deadlocking or losing a result."""
    shared_instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY)'})
    results: list[dict] = []
    errors: list[BaseException] = []

    def _refresh():
        try:
            results.append(shared_instance.refresh_schema({}))
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(exc)

    threads = [threading.Thread(target=_refresh) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 4
    assert all('widgets' in result['tables'] for result in results)


def test_refresh_schema_invalidates_the_insert_lane_column_map(instance):
    """The answers lane must be as current as the tool's own return value.

    ``refresh_schema`` replaces ``IGlobal.db_schema`` (what the LLM path
    describes) but ``_insertData`` builds every INSERT from ``IGlobal.schema``,
    a separate start-up snapshot of the configured table. Leaving that behind
    made the node current on one path and stale on the other: a column added
    by the very DDL that prompted the refresh would still be dropped.
    """
    iglobal = instance.IGlobal
    iglobal.table = 'widgets'

    instance.execute({'sql': 'CREATE TABLE widgets (label TEXT)'})
    # Start-up state: beginGlobal reflected the one-column table.
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('widgets')}
    assert set(iglobal.schema) == {'label'}

    instance.execute({'sql': 'ALTER TABLE widgets ADD COLUMN size INTEGER'})
    instance.refresh_schema({})

    # Invalidated, so _insertData re-reflects on its next call.
    assert iglobal.schema == {}

    instance._insertData([{'label': 'a', 'size': 7}])

    assert instance.execute({'sql': 'SELECT label, size FROM widgets'})['rows'] == [{'label': 'a', 'size': 7}]
    assert set(iglobal.schema) == {'label', 'size'}


def test_insert_lane_drops_a_new_column_without_a_refresh(instance):
    """Pins why the invalidation above is needed, not just that it happens."""
    iglobal = instance.IGlobal
    iglobal.table = 'widgets'

    instance.execute({'sql': 'CREATE TABLE widgets (label TEXT)'})
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('widgets')}

    instance.execute({'sql': 'ALTER TABLE widgets ADD COLUMN size INTEGER'})
    # No refresh_schema call: the stale map still has only `label`.
    instance._insertData([{'label': 'a', 'size': 7}])

    assert instance.execute({'sql': 'SELECT label, size FROM widgets'})['rows'] == [{'label': 'a', 'size': None}]


def test_refresh_schema_empties_the_column_map_when_the_table_is_gone(instance):
    """A dropped configured table leaves a falsy map, matching task start."""
    iglobal = instance.IGlobal
    iglobal.table = 'widgets'

    instance.execute({'sql': 'CREATE TABLE widgets (label TEXT)'})
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('widgets')}

    instance.execute({'sql': 'DROP TABLE widgets'})
    instance.refresh_schema({})

    assert iglobal.schema == {}


# ---------------------------------------------------------------------------
# execute() must not echo the statement or its bind parameters
# ---------------------------------------------------------------------------


def test_execute_error_does_not_leak_the_statement_or_parameters(instance):
    """A failed statement reports the driver message, never [SQL:]/[parameters:].

    ``str()`` of a SQLAlchemy StatementError appends the executed statement
    and the values bound into it. That used to stay in the server log; since
    ``execute`` re-raises the formatted message to its caller, the whole repr
    would reach a user-facing Run/Refresh UI. Runs against the real sqlite3
    driver, so it pins the actual exception shape rather than a fake.
    """
    instance.execute({'sql': 'CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)'})

    with pytest.raises(RuntimeError) as excinfo:
        instance.execute({'sql': 'SELECT no_such_column FROM users WHERE email = $1', 'params': ['ada@example.com']})

    message = str(excinfo.value)
    assert message == 'SQL execution failed: no such column: no_such_column'
    assert 'ada@example.com' not in message
    assert '[SQL:' not in message
    assert '[parameters:' not in message
    assert 'sqlalche.me' not in message


# ---------------------------------------------------------------------------
# The answers lane must not bind a database-generated primary key
# ---------------------------------------------------------------------------


def _compiled_insert_columns(instance, items):
    """Return the column names an _insertData batch would actually bind.

    SQLAlchemy builds the INSERT from the first mapping in the executemany
    list, so capturing the compiled statement is the only way to assert on the
    column list rather than on whatever the database happened to tolerate.
    """
    captured: list[str] = []
    engine = instance.IGlobal.engine

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('INSERT'):
            captured.append(statement)

    event.listen(engine, 'before_cursor_execute', _before_cursor_execute)
    try:
        instance._insertData(items)
    finally:
        event.remove(engine, 'before_cursor_execute', _before_cursor_execute)

    assert captured, 'no INSERT reached the driver'
    statement = captured[0]
    inside = statement[statement.index('(') + 1 : statement.index(')')]
    return [name.strip().strip('"').strip('`') for name in inside.split(',')]


def test_insert_after_refresh_does_not_bind_the_generated_primary_key(instance):
    """refresh_schema must not change what an auto-created table inserts.

    ``_createTableFromData`` prepends an auto-increment ``id`` and then caches
    the DATA columns only, because the database generates the key. Refreshing
    replaces that curated map with a plain reflection that includes ``id``;
    without the guard in ``_insertData`` every later row would bind ``id=None``
    -- harmless on SQLite's rowid alias, a not-null violation against the
    ``id SERIAL NOT NULL`` Postgres renders for the same column.
    """
    iglobal = instance.IGlobal
    iglobal.table = 'answers'

    # Auto-create through the real path, then confirm the curated map.
    instance._insertData([{'q': 'why', 'a': 'because'}])
    assert set(iglobal.schema) == {'q', 'a'}

    instance.refresh_schema({})
    # The rebuilt map is a full reflection, primary key included ...
    instance._insertData([{'q': 'how', 'a': 'like this'}])
    assert set(iglobal.schema) == {'id', 'q', 'a'}

    # ... but the INSERT still carries the data columns only.
    columns = _compiled_insert_columns(instance, [{'q': 'when', 'a': 'now'}])
    assert 'id' not in columns
    assert set(columns) == {'q', 'a'}

    rows = instance.execute({'sql': 'SELECT id, q FROM answers ORDER BY id'})['rows']
    assert [row['q'] for row in rows] == ['why', 'how', 'when']
    assert all(row['id'] is not None for row in rows)


def test_insert_omits_a_reflected_primary_key_the_rows_do_not_supply(instance):
    """The same guard covers a table that already existed at task start.

    ``beginGlobal`` reflects the configured table, so its map has always
    carried the primary key; binding NULL into it was a pre-existing defect
    that the refresh path would otherwise have widened to auto-created tables.
    """
    iglobal = instance.IGlobal
    iglobal.table = 'widgets'

    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT)'})
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('widgets')}
    assert set(iglobal.schema) == {'id', 'label'}

    columns = _compiled_insert_columns(instance, [{'label': 'a'}])
    assert columns == ['label']


def test_insert_still_binds_a_primary_key_the_rows_do_supply(instance):
    """An explicit key is the caller's to set; the guard must not swallow it."""
    iglobal = instance.IGlobal
    iglobal.table = 'widgets'

    instance.execute({'sql': 'CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT)'})
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('widgets')}

    columns = _compiled_insert_columns(instance, [{'id': 42, 'label': 'a'}])
    assert set(columns) == {'id', 'label'}
    assert instance.execute({'sql': 'SELECT id FROM widgets'})['rows'] == [{'id': 42}]


def test_insert_binds_the_primary_key_when_it_is_the_only_column(instance):
    """Omitting every column would build empty mappings, so fall back."""
    iglobal = instance.IGlobal
    iglobal.table = 'ids'

    instance.execute({'sql': 'CREATE TABLE ids (id INTEGER PRIMARY KEY)'})
    iglobal.schema = {name: (col_type, '') for name, col_type in iglobal._getTableSchema('ids')}

    columns = _compiled_insert_columns(instance, [{'label': 'ignored'}])
    assert columns == ['id']
