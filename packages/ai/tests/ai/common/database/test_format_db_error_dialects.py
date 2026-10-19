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

"""``_format_db_error`` against the messages MySQL 8.4 and ClickHouse 25.8 really send.

Unless its test says it is constructed, every message below was captured from
a live server (MySQL 8.4.11, ClickHouse 25.8.33.6) by a native client
(pymysql, clickhouse-driver), for the statement given next to it. Only the
ClickHouse stack trace is shortened, to its first two frames: the stripper
cuts at its header, so the frames after that are irrelevant. Neither
clickhouse-driver nor clickhouse-sqlalchemy is installed in this suite, so the
exception objects carrying the messages are stand-ins of the same shape (code
on ``.code``, text on ``.message``, wrapped in ``.orig``).

Two separate defects, pinned in both directions:

- ClickHouse echoes the statement, with the client-interpolated bind values in
  it, in three more places than the markers covered: a named CTE or lambda
  scope (``in scope x AS (SELECT ...)``, ``in scope x -> ...``), code 215's
  ``In query SELECT ...``, and a mutation's ``while processing: '<expr>'``.
- The markers of one dialect cut another's text: a MySQL ``SIGNAL`` message
  reading "Upload failed at position 3 of batch" came back as "Upload", and a
  ClickHouse ``throwIf`` message reading "In scope SELECT secret" came back
  as nothing at all.

Separate module from ``test_db_base.py`` for the reason
``test_db_execute_errors.py`` gives: that file is appended to by more than one
open pull request.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy.exc import DBAPIError

from ai.common.database.db_global_base import DatabaseGlobalBase
from ai.common.database.db_instance_base import DatabaseInstanceBase


# ---------------------------------------------------------------------------
# Stand-ins and fixtures
# ---------------------------------------------------------------------------


class _TestableGlobal(DatabaseGlobalBase):
    """Concrete DatabaseGlobalBase; the connection methods are never called here."""

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


class _PyMySQLError(Exception):
    """Stand-in for pymysql's ``OperationalError``: ``args`` is ``(errno, message)``."""


class _DriverError(Exception):
    """Stand-in for a driver this module does not identify: ``args`` is ``(message,)``."""


class _ClickHouseServerException(Exception):
    """Stand-in for ``clickhouse_driver.errors.ServerException``.

    The code lives on ``.code`` and the server's text on ``.message``, which is
    what the db_clickhouse node's formatter branch reads.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class _ClickHouseDatabaseException(Exception):
    """Stand-in for ``clickhouse_sqlalchemy.exceptions.DatabaseException``.

    What ``clickhouse+native://`` raises: a plain ``Exception`` -- not a DBAPI
    error -- carrying the driver's exception on ``.orig``.
    """

    def __init__(self, orig):
        super().__init__(orig)
        self.orig = orig

    def __str__(self):
        """Prefix the wrapped driver error, as the real class does."""
        return f'Orig exception: {self.orig}'


# The first two frames of the trace ClickHouse 25.8.33.6 appended to every
# message below; the rest of each trace is dropped (see the module docstring).
_CLICKHOUSE_STACK_TRACE = (
    '. Stack trace:\n\n'
    '0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000011001070\n'
    '1. DB::Exception::Exception(String&&, int, String, bool) @ 0x000000000ba29158\n'
)


def _clickhouse(code, message):
    """The exception the db_clickhouse node sees for a server message, trace appended."""
    return _ClickHouseDatabaseException(_ClickHouseServerException(code, message + _CLICKHOUSE_STACK_TRACE))


class _ClickHouseDbapiError(Exception):
    """Stand-in for ``clickhouse_driver.dbapi``'s ``OperationalError(ServerException)``.

    That layer's error carries the driver's ``ServerException`` as the only
    element of its ``args``, with no ``.code`` of its own.
    """


def _mysql(errno, message):
    """A pymysql error wrapped the way SQLAlchemy wraps one it catches."""
    return DBAPIError.instance('SELECT 1', {}, _PyMySQLError(errno, message), dbapi_base_err=Exception)


class _FailingConnection:
    """Connection stand-in whose execute() always raises the given exception."""

    def __init__(self, exc):
        self._exc = exc

    def execute(self, *args, **kwargs):
        """Fail the way a driver fails, with the statement already bound."""
        raise self._exc


class _FailingEngine:
    """Engine stand-in whose begin() hands out a connection that always raises."""

    def __init__(self, exc):
        self._exc = exc

    @contextlib.contextmanager
    def begin(self):
        """Yield the failing connection, mirroring engine.begin()'s contract."""
        yield _FailingConnection(self._exc)


@pytest.fixture
def base():
    """A bare global; ``_format_db_error`` needs no engine."""
    return _TestableGlobal.__new__(_TestableGlobal)


def _execute_error(exc):
    """What the ``execute`` tool raises to its caller when the driver raises ``exc``."""
    iglobal = _TestableGlobal.__new__(_TestableGlobal)
    iglobal.engine = _FailingEngine(exc)
    iglobal.allow_execute = True
    iglobal.max_execute_rows = 1000
    inst = _TestableInstance.__new__(_TestableInstance)
    inst.IGlobal = iglobal
    with pytest.raises(RuntimeError) as excinfo:
        inst.execute({'sql': 'SELECT 1'})
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# ClickHouse: the three statement echoes the markers missed
#
# clickhouse-driver interpolates bind values client-side, so each echo below
# carries the value the caller bound to $1 (the QA_CANARY_* literal).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('message', 'expected', 'canary'),
    [
        # WITH x AS (SELECT nope_col FROM qa_lead_r_orders WHERE qa_mark = $1) SELECT * FROM x
        (
            'DB::Exception: Unknown expression identifier `nope_col` in scope x AS (SELECT nope_col '
            "FROM qa_lead_r_orders WHERE qa_mark = 'QA_CANARY_LEAD_R1')",
            'Error 47: DB::Exception: Unknown expression identifier `nope_col`',
            'QA_CANARY_LEAD_R1',
        ),
        # WITH t AS (SELECT nope FROM qa_da_events WHERE s = $1) SELECT * FROM t
        (
            "DB::Exception: Unknown expression identifier `nope` in scope t AS (SELECT nope FROM qa_da_events WHERE s = 'QA_CANARY_DA_42')",
            'Error 47: DB::Exception: Unknown expression identifier `nope`',
            'QA_CANARY_DA_42',
        ),
        # WITH a AS (SELECT 1 AS x), b AS (SELECT nope_cn FROM a WHERE $1 = $1) SELECT * FROM b
        (
            'DB::Exception: Unknown expression identifier `nope_cn` in scope b AS (SELECT nope_cn FROM a '
            "WHERE 'QA_CANARY_CH_4101' = 'QA_CANARY_CH_4101')",
            'Error 47: DB::Exception: Unknown expression identifier `nope_cn`',
            'QA_CANARY_CH_4101',
        ),
    ],
    ids=['cte-x', 'cte-t', 'second-cte'],
)
def test_clickhouse_cuts_a_named_cte_scope_echo(base, message, expected, canary):
    """A CTE body is echoed as ``in scope <name> AS (SELECT ...)``.

    The marker only knew the unnamed form, ``in scope (SELECT ...)``, which
    ClickHouse 25.8 prints for a scalar subquery; a named CTE puts its name and
    ``AS`` in front of the parenthesis, so the lookahead missed it.
    """
    result = base._format_db_error(_clickhouse(47, message))

    assert result == expected
    assert canary not in result
    assert 'in scope' not in result


def test_clickhouse_cuts_a_lambda_scope_echo(base):
    """A lambda body is echoed as ``in scope <arg> -> <body>``.

    ``SELECT arrayMap(x -> concat(x, $1, nope), ['a'])`` with ``$1`` bound to
    ``QA_CANARY_DA_41``.
    """
    exc = _clickhouse(
        47,
        "DB::Exception: Unknown expression or function identifier `nope` in scope x -> concat(x, 'QA_CANARY_DA_41', nope)",
    )

    result = base._format_db_error(exc)

    assert result == 'Error 47: DB::Exception: Unknown expression or function identifier `nope`'
    assert 'QA_CANARY_DA_41' not in result


def test_clickhouse_cuts_a_multi_argument_lambda_scope_echo(base):
    """A lambda over several arguments prints them as a tuple: ``(x, y) -> ...``.

    ``SELECT arrayMap((x, y) -> concat(x, y, $1, nope), ['a'], ['b'])`` with
    ``$1`` bound to ``QA_CANARY_LAMBDA_2``: ClickHouse's formatter prints a
    one-element lambda tuple as its bare element and any other as a
    parenthesised list.
    """
    exc = _clickhouse(
        47,
        'DB::Exception: Unknown expression or function identifier `nope` in scope '
        "(x, y) -> concat(x, y, 'QA_CANARY_LAMBDA_2', nope)",
    )

    result = base._format_db_error(exc)

    assert result == 'Error 47: DB::Exception: Unknown expression or function identifier `nope`'
    assert 'QA_CANARY_LAMBDA_2' not in result


def test_clickhouse_cuts_the_in_query_echo_of_code_215(base):
    """NOT_AN_AGGREGATE ends its sentence and repeats the statement after ``In query``.

    ``SELECT order_id, count() FROM qa_lead_r_orders WHERE qa_mark = $1 GROUP
    BY customer`` with ``$1`` bound to ``QA_CANARY_LEAD_R2``.
    """
    exc = _clickhouse(
        215,
        "DB::Exception: Column 'qa_sql_6f5672_lead.qa_lead_r_orders.order_id' is not under aggregate function "
        "and not in GROUP BY keys. In query SELECT order_id, count() FROM qa_lead_r_orders WHERE qa_mark = 'QA_CANARY_LEAD_R2' "
        'GROUP BY customer',
    )

    result = base._format_db_error(exc)

    assert result == (
        "Error 215: DB::Exception: Column 'qa_sql_6f5672_lead.qa_lead_r_orders.order_id' is not under "
        'aggregate function and not in GROUP BY keys.'
    )
    assert 'QA_CANARY_LEAD_R2' not in result
    assert 'In query' not in result


def test_clickhouse_cuts_an_in_query_echo_of_a_cte_body(base):
    """``In query`` formats its query node like ``in scope`` does, CTE name included.

    ``WITH x AS (SELECT order_id, count() FROM t WHERE qa_mark = $1 GROUP BY
    customer) SELECT * FROM x`` with ``$1`` bound to ``QA_CANARY_IN_QUERY_CTE``.
    """
    exc = _clickhouse(
        215,
        "DB::Exception: Column 'qa.t.order_id' is not under aggregate function and not in GROUP BY keys. "
        "In query x AS (SELECT order_id, count() FROM t WHERE qa_mark = 'QA_CANARY_IN_QUERY_CTE' GROUP BY customer)",
    )

    result = base._format_db_error(exc)

    assert result == (
        "Error 215: DB::Exception: Column 'qa.t.order_id' is not under aggregate function and not in GROUP BY keys."
    )
    assert 'QA_CANARY_IN_QUERY_CTE' not in result


def test_clickhouse_cuts_the_old_interpreters_while_processing_echo(base):
    """The pre-analyzer interpreter appends ``: While processing <expr>``.

    ``SELECT * FROM t WHERE isZeroOrNull(nofunc(qa_mark) = $1) SETTINGS
    enable_analyzer = 0`` with ``$1`` bound to ``QA_CANARY_OLD``. The old
    interpreter also runs on servers before 24.3 and on some mutation paths.
    The expression it repeats carries the bound value like every other echo
    here.
    """
    exc = _clickhouse(
        46,
        "DB::Exception: Unknown function nofunc: While processing isZeroOrNull(nofunc(qa_mark) = 'QA_CANARY_OLD')",
    )

    result = base._format_db_error(exc)

    assert result == 'Error 46: DB::Exception: Unknown function nofunc'
    assert 'QA_CANARY_OLD' not in result


@pytest.mark.parametrize(
    ('message', 'expected', 'canary'),
    [
        # ALTER TABLE qa_lead_r_orders DELETE WHERE nope_col = 1 AND qa_mark = $1
        (
            "DB::Exception: Missing columns: 'nope_col' while processing: 'isZeroOrNull((nope_col = 1) AND "
            "(qa_mark = 'QA_CANARY_LEAD_R3')), _block_number, _distance, _part_data_version, _part_offset, "
            '_disk_name, _sample_factor, _partition_id, _part_starting_offset, _part, _part_index, customer, '
            "_part_granule_offset, _block_offset, _part_uuid, qa_mark, order_id', required columns: 'nope_col' "
            "'_part_starting_offset' 'qa_mark' '_block_offset' '_part_uuid' '_block_number' '_part_data_version' "
            "'_distance' '_partition_id' '_part_offset' '_disk_name' '_sample_factor' 'customer' '_part' "
            "'_part_index' '_part_granule_offset' 'order_id', maybe you meant: 'qa_mark', 'customer' or 'order_id'",
            "Error 47: DB::Exception: Missing columns: 'nope_col'",
            'QA_CANARY_LEAD_R3',
        ),
        # DELETE FROM qa_cht_orders WHERE nope_dl = 1 AND qa_mark = $1 (lightweight DELETE)
        (
            "DB::Exception: Missing columns: 'nope_dl' while processing: '_CAST(if((nope_dl = 1) AND "
            "(qa_mark = 'QA_CANARY_CH_4102'), _CAST(0, 'UInt8'), _row_exists), 'UInt8'), _row_exists', "
            "required columns: 'nope_dl' 'qa_mark' '_row_exists', maybe you meant: 'qa_mark'",
            "Error 47: DB::Exception: Missing columns: 'nope_dl'",
            'QA_CANARY_CH_4102',
        ),
    ],
    ids=['alter-delete', 'lightweight-delete'],
)
def test_clickhouse_cuts_a_mutation_while_processing_echo(base, message, expected, canary):
    """A mutation repeats its rewritten predicate after ``while processing: '``.

    The marker knew the SELECT form, ``while processing query:``. A mutation
    has no query to name, so the old parser prints the expression it was
    building instead -- with the caller's bound value in it.
    """
    result = base._format_db_error(_clickhouse(47, message))

    assert result == expected
    assert canary not in result
    assert 'while processing' not in result


@pytest.mark.parametrize(
    ('message', 'expected', 'canaries'),
    [
        # INSERT INTO t (n, s) VALUES ($1, $2), ($3), ($4, $5) -- row 2 is missing a value
        (
            "DB::Exception: Cannot parse expression of type UInt32 here: 2), (3, 'QA_CANARY_ROW3'): "
            'While executing ValuesBlockInputFormat',
            'Error 62: DB::Exception: Cannot parse expression of type UInt32',
            ['QA_CANARY_ROW3'],
        ),
        # INSERT INTO t (n, s) VALUES ($1), ($2, $3) -- row 1 is missing a value
        (
            "DB::Exception: Cannot parse expression of type UInt32 here: 1), (2, 'QA_CANARY_AFTER'): "
            'While executing ValuesBlockInputFormat',
            'Error 62: DB::Exception: Cannot parse expression of type UInt32',
            ['QA_CANARY_AFTER'],
        ),
        # SELECT toDate($1)
        (
            'DB::Exception: Cannot parse date here: QA_CANARY_: Cannot parse Date from String: '
            "In scope SELECT toDate('QA_CANARY_TODATE')",
            'Error 38: DB::Exception: Cannot parse date',
            ['QA_CANARY_'],
        ),
        # INSERT INTO t (n, s) VALUES ($1, $2, $3), ($4, $5) -- an extra value in row 1
        (
            "DB::Exception: Cannot parse expression of type String here: 'QA_CANARY_ROW1', 'QA_CANARY_EXTRA'), "
            "(70022, 'QA_CANARY_ROW2'): While executing ValuesBlockInputFormat",
            'Error 62: DB::Exception: Cannot parse expression of type String',
            ['QA_CANARY_ROW1', 'QA_CANARY_EXTRA', 'QA_CANARY_ROW2'],
        ),
        # INSERT INTO t (n, s) VALUES ($1, $2, ($3, $4) -- row 1 not closed
        (
            "DB::Exception: Cannot parse expression of type String here: 'QA_CANARY_ROW1', (70022, 'QA_CANARY_ROW2'): "
            'While executing ValuesBlockInputFormat',
            'Error 62: DB::Exception: Cannot parse expression of type String',
            ['QA_CANARY_ROW1', 'QA_CANARY_ROW2'],
        ),
    ],
    ids=['values-row-2', 'values-row-1', 'todate', 'values-extra-value', 'values-row-not-closed'],
)
def test_clickhouse_cuts_the_input_a_parser_prints_after_here(base, message, expected, canaries):
    """A parser that stopped prints the rest of its input after `` here: ``.

    For ``INSERT ... VALUES`` that is every later row, with the values bound
    into them. The code is set below to the one each message was captured with.
    """
    code = int(expected.split(':')[0].split()[1])

    result = base._format_db_error(_clickhouse(code, message))

    assert result == expected
    for canary in canaries:
        assert canary not in result


@pytest.mark.parametrize(
    ('message', 'expected', 'canaries'),
    [
        # INSERT INTO t (n, s) VALUES ($1, $2) ON DUPLICATE KEY UPDATE s = $3 -- another dialect's upsert
        (
            "DB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_UPSERT_S2\\'':  at row 1: While executing ValuesBlockInputFormat. ",
            "Error 27: DB::Exception: Cannot parse input: expected '('",
            ['QA_CANARY_UPSERT_S2'],
        ),
        # INSERT INTO t (n, s) VALUES ($1, $2), $3, $4 -- second row without parentheses
        (
            "DB::Exception: Cannot parse input: expected '(' before: '70022, \\'QA_CANARY_ROW2\\'':  at row 1: While executing ValuesBlockInputFormat. ",
            "Error 27: DB::Exception: Cannot parse input: expected '('",
            ['QA_CANARY_ROW2', '70022'],
        ),
        # INSERT INTO t (n, s) VALUES ($1, $2) ON CONFLICT (n) DO UPDATE SET s = $3
        (
            "DB::Exception: Cannot parse input: expected '(' before: 'ON CONFLICT (n) DO UPDATE SET s = \\'QA_CANARY_PGUP_S2\\'':  at row 1: While executing ValuesBlockInputFormat. ",
            "Error 27: DB::Exception: Cannot parse input: expected '('",
            ['QA_CANARY_PGUP_S2'],
        ),
        # INSERT INTO t (n, s) VALUES ($1, $2) ON DUPLICATE KEY UPDATE s = $3, with a 300-character $3
        (
            "DB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_LONG_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx':  at row 1: While executing ValuesBlockInputFormat. ",
            "Error 27: DB::Exception: Cannot parse input: expected '('",
            ['QA_CANARY_LONG_'],
        ),
        # INSERT INTO t (n, s) FORMAT CSV $1,$2\nabc,$3\n -- bad UInt32 in row 2
        (
            'DB::Exception: Cannot parse input: expected \',\' before: \'abc,\\\'QA_CANARY_ROW2\\\'\\n\': (at row 2)\n: \nRow 1:\nColumn 0,   name: n, type: UInt32, parsed text: "70011"\nColumn 1,   name: s, type: String, parsed text: "<SINGLE QUOTE>QA_CANARY_ROW1<SINGLE QUOTE>"\n\nRow 2:\nColumn 0,   name: n, type: UInt32, ERROR: text "abc,<SINGLE QUOTE>QA_CA" is not like UInt32\n\n: While executing ParallelParsingBlockInputFormat. ',
            "Error 27: DB::Exception: Cannot parse input: expected ','",
            ['QA_CANARY_ROW1', 'QA_CANARY_ROW2', '70011'],
        ),
    ],
    ids=['mysql-upsert', 'row-without-parentheses', 'postgres-upsert', 'truncated-tail', 'format-csv'],
)
def test_clickhouse_cuts_the_input_a_parser_prints_after_before(base, message, expected, canaries):
    """A row that is not followed by ``,`` or ``(`` echoes the rest of the input after `` before: '``.

    Code 27 (CANNOT_PARSE_INPUT_ASSERTION_FAILED) quotes every later bound
    value, and for ``FORMAT CSV`` adds per-row ``parsed text`` lines that
    repeat the earlier rows' values too.
    """
    result = base._format_db_error(_clickhouse(27, message.rstrip('. ')))

    assert result == expected
    for canary in canaries:
        assert canary not in result


def test_clickhouse_cuts_the_before_echo_over_the_mysql_wire(base):
    """The same echo through ClickHouse's MySQL interface, as pymysql's ``(errno, message)``.

    ``INSERT INTO t (n, s) VALUES (%s, %s) ON DUPLICATE KEY UPDATE s = %s``
    on port 9004.
    """
    exc = _mysql(
        27,
        "Code: 27. DB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_UPSERT_S2\\'':  at row 1: While executing ValuesBlockInputFormat. (CANNOT_PARSE_INPUT_ASSERTION_FAILED) (version 25.8.33.6 (official build))",
    )

    result = base._format_db_error(exc)

    assert result == "Error 27: DB::Exception: Cannot parse input: expected '('"
    assert 'QA_CANARY_UPSERT_S2' not in result


def test_clickhouse_cuts_a_function_call_scope_echo(base):
    """An expression evaluated on its own is echoed as ``In scope f(...)``.

    ``INSERT INTO t (n, s) VALUES ($1, $2), (nofunc($3), $4), ($5, $6)`` with
    ``$3`` bound to ``QA_CANARY_FNARG``.
    """
    exc = _clickhouse(
        46,
        "DB::Exception: Function with name `nofunc` does not exist. In scope nofunc('QA_CANARY_FNARG'): "
        'While executing ValuesBlockInputFormat',
    )

    result = base._format_db_error(exc)

    assert result == 'Error 46: DB::Exception: Function with name `nofunc` does not exist.'
    assert 'QA_CANARY_FNARG' not in result


def test_clickhouse_keeps_a_bad_value_in_a_well_formed_values_row(base):
    """Unchanged: a value the parser could read but not convert is named, nothing more.

    ``INSERT INTO t (n, s) VALUES ($1, $2), ($3, $4), ($5, $6)`` with ``$3``
    bound to ``'abc'`` and canaries in rows 1 and 3. ClickHouse evaluates the
    value as an expression and reports only it, with a runtime context.
    """
    message = (
        "DB::Exception: Cannot parse string 'abc' as UInt32: syntax error at begin of string. Note: there are "
        'toUInt32OrZero and toUInt32OrNull functions, which returns zero/NULL instead of throwing exception: '
        "while executing 'FUNCTION if(isNull(-dummy-0) : 3, defaultValueOfTypeName('UInt32') :: 2, "
        "_CAST(-dummy-0, 'UInt32') :: 4) -> if(isNull(-dummy-0), defaultValueOfTypeName('UInt32'), "
        "_CAST(-dummy-0, 'UInt32')) UInt32 : 1': While executing ValuesBlockInputFormat"
    )

    assert base._format_db_error(_clickhouse(6, message)) == f'Error 6: {message}.'


@pytest.mark.parametrize(
    ('message', 'code', 'expected'),
    [
        (
            'DB::Exception: Unknown expression identifier `nope_col` in scope x AS (SELECT nope_col '
            "FROM qa_lead_r_orders WHERE qa_mark = 'QA_CANARY_LEAD_R1')",
            47,
            'Error 47: DB::Exception: Unknown expression identifier `nope_col`',
        ),
        (
            "DB::Exception: In scope SELECT secret: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
            "'In scope SELECT secret'_String :: 2) -> throwIf(1_UInt8, 'In scope SELECT secret'_String) UInt8 : 3'",
            395,
            'Error 395: DB::Exception: In scope SELECT secret',
        ),
    ],
    ids=['cte-echo', 'throwif'],
)
def test_clickhouse_dbapi_layer_reaches_the_same_branch(base, message, code, expected):
    """``clickhouse_driver.dbapi`` is unwrapped to its ``ServerException`` first.

    The captured messages above, through the other connector layer. Before,
    its ``args`` held the exception object, so it fell through to ``str(orig)``
    and the backstop markers, which no longer carry the ClickHouse-only ones.
    """
    server = _ClickHouseServerException(code, message + _CLICKHOUSE_STACK_TRACE)
    exc = DBAPIError.instance('SELECT 1', {}, _ClickHouseDbapiError(server), dbapi_base_err=Exception)

    assert base._format_db_error(exc) == expected


class _CodedDriverError(Exception):
    """Stand-in for a driver other than ClickHouse's that also puts ``.code`` and ``.message`` on its error."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


_POSTGRES_SHAPED_TEXT = (
    'duplicate key value violates unique constraint "u_email"\n'
    'DETAIL:  Key (email)=(QA_CANARY_CODED@x.io) already exists.'
)


def test_a_code_and_message_pair_that_is_not_clickhouses_keeps_the_backstop(base):
    """``.code`` / ``.message`` is not ClickHouse's shape alone, so neither are its markers.

    Constructed: text that does not open with ``DB::Exception:`` is cut with
    every dialect's markers, as before, so a PostgreSQL-style DETAIL block
    still goes.
    """
    exc = DBAPIError.instance('SELECT 1', {}, _CodedDriverError(23505, _POSTGRES_SHAPED_TEXT), dbapi_base_err=Exception)

    result = base._format_db_error(exc)

    assert result == 'Error 23505: duplicate key value violates unique constraint "u_email"'
    assert 'QA_CANARY_CODED' not in result


def test_a_wrapped_error_that_is_not_clickhouses_is_not_unwrapped(base):
    """Only ClickHouse's text is unwrapped from a one-element ``args``.

    Constructed: another driver wrapping its own coded error the way
    ``clickhouse_driver.dbapi`` does keeps the old path, ``str(orig)`` and the
    backstop, so the DETAIL block is still cut.
    """
    wrapper = _ClickHouseDbapiError(_CodedDriverError(23505, _POSTGRES_SHAPED_TEXT))
    exc = DBAPIError.instance('SELECT 1', {}, wrapper, dbapi_base_err=Exception)

    result = base._format_db_error(exc)

    assert result == 'duplicate key value violates unique constraint "u_email"'
    assert 'QA_CANARY_CODED' not in result


def test_execute_reports_a_clickhouse_scope_echo_without_the_bound_value():
    """The same cut as the caller of the ``execute`` tool sees it."""
    message = _execute_error(
        _clickhouse(
            47,
            'DB::Exception: Unknown expression identifier `nope_col` in scope x AS (SELECT nope_col '
            "FROM qa_lead_r_orders WHERE qa_mark = 'QA_CANARY_LEAD_R1')",
        )
    )

    assert message == 'SQL execution failed: Error 47: DB::Exception: Unknown expression identifier `nope_col`'


# ---------------------------------------------------------------------------
# MySQL: no ClickHouse or PostgreSQL marker applies to MySQL's own text
#
# The MySQL README promises the primary sentence "as MySQL wrote it". Every
# message below is a SIGNAL's MESSAGE_TEXT or MySQL's own syntax-error
# sentence, so each is returned whole.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'text',
    [
        'Upload failed at position 3 of batch',
        'Retry later. Stack trace: unavailable',
        'Bad CSV. LINE 2: unterminated quote',
        'Column not in scope SELECT list',
        'Missing input, required columns: a, b',
        'line one\nDETAIL: injected second line',
        'Order rejected.\nHINT: contact billing',
    ],
    ids=['failed-at-position', 'stack-trace', 'line-n', 'in-scope', 'required-columns', 'detail', 'hint'],
)
def test_mysql_keeps_a_signal_message_that_contains_another_dialects_marker(base, text):
    """``SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '<text>'`` -> pymysql ``(1644, '<text>')``."""
    assert base._format_db_error(_mysql(1644, text)) == f'Error 1644: {text}'


@pytest.mark.parametrize(
    'text',
    [
        "Rejected while processing: 'batch 3'",
        'Rejected in query SELECT path',
        'Rejected in scope x AS (SELECT list)',
    ],
    ids=['while-processing', 'in-query', 'in-scope-cte'],
)
def test_mysql_keeps_a_signal_message_that_contains_a_new_clickhouse_marker(base, text):
    """The markers added for ClickHouse's echoes do not reach MySQL either.

    One SIGNAL text per marker this change adds, sent the same way as the ones
    above.
    """
    assert base._format_db_error(_mysql(1644, text)) == f'Error 1644: {text}'


def test_an_errno_message_pair_keeps_sqlalchemys_markers(base):
    """The ``(int, str)`` branch keeps a strip: SQLAlchemy's markers, and no other dialect's.

    Constructed: a driver of pymysql's shape that is not pymysql, carrying a
    SQLAlchemy-style tail in its own message. Only those markers apply here,
    so MySQL's own sentences above stay whole.
    """
    exc = _mysql(1, "boom\n[SQL: SELECT secret FROM t WHERE token = 'QA_CANARY_ERRNO']")

    assert base._format_db_error(exc) == 'Error 1: boom'


@pytest.mark.parametrize(
    'fragment',
    ["'LINE 1: x'", "'Stack trace: x'", "'in scope SELECT'"],
    ids=['line-n', 'stack-trace', 'in-scope'],
)
def test_mysql_keeps_its_own_near_fragment_whole(base, fragment):
    """``SELEC <fragment> FROM qa_my_customers`` -> 1064, quoting the statement it stopped on.

    The README documents that this quote passes through; it was cut at the
    first marker inside it instead, mid-quote.
    """
    text = (
        'You have an error in your SQL syntax; check the manual that corresponds to your MySQL server '
        f"version for the right syntax to use near 'SELEC {fragment} FROM qa_my_customers' at line 1"
    )

    assert base._format_db_error(_mysql(1064, text)) == f'Error 1064: {text}'


@pytest.mark.parametrize(
    ('errno', 'message', 'expected', 'canary'),
    [
        # SELECT nope FROM t WHERE s = %s
        (
            47,
            'Code: 47. DB::Exception: Unknown expression identifier `nope` in scope SELECT nope FROM t WHERE '
            "s = 'QA_CANARY_MYIF_1A'. (UNKNOWN_IDENTIFIER) (version 25.8.33.6 (official build))",
            'Error 47: DB::Exception: Unknown expression identifier `nope`',
            'QA_CANARY_MYIF_1A',
        ),
        # WITH x AS (SELECT nope FROM t WHERE s = %s) SELECT * FROM x
        (
            47,
            'Code: 47. DB::Exception: Unknown expression identifier `nope` in scope x AS (SELECT nope FROM t '
            "WHERE s = 'QA_CANARY_MYIF_1B'). (UNKNOWN_IDENTIFIER) (version 25.8.33.6 (official build))",
            'Error 47: DB::Exception: Unknown expression identifier `nope`',
            'QA_CANARY_MYIF_1B',
        ),
        # SELECT throwIf(1, 'In scope SELECT secret')
        (
            395,
            "Code: 395. DB::Exception: In scope SELECT secret: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
            "'In scope SELECT secret'_String :: 2) -> throwIf(1_UInt8, 'In scope SELECT secret'_String) UInt8 : 3'. "
            '(FUNCTION_THROW_IF_VALUE_IS_NON_ZERO) (version 25.8.33.6 (official build))',
            'Error 395: DB::Exception: In scope SELECT secret',
            None,
        ),
        # SELECT throwIf(1, 'Upload failed at position 3 of batch')
        (
            395,
            'Code: 395. DB::Exception: Upload failed at position 3 of batch: while executing '
            "'FUNCTION throwIf(1_UInt8 :: 1, 'Upload failed at position 3 of batch'_String :: 2) -> "
            "throwIf(1_UInt8, 'Upload failed at position 3 of batch'_String) UInt8 : 3'. "
            '(FUNCTION_THROW_IF_VALUE_IS_NON_ZERO) (version 25.8.33.6 (official build))',
            'Error 395: DB::Exception: Upload failed at position 3 of batch',
            None,
        ),
    ],
    ids=['scope-echo', 'cte-echo', 'throwif-scope-words', 'throwif-tail-words'],
)
def test_clickhouse_text_over_the_mysql_wire_gets_clickhouses_markers(base, errno, message, expected, canary):
    """db_mysql pointed at ClickHouse's MySQL interface (port 9004) gets pymysql's ``(errno, message)``.

    The pair says which protocol carried the error, not which server wrote
    it: the text is ClickHouse's, statement echo and bound value included, so
    it is cut as ClickHouse's text is -- ``throwIf`` exception and all. The
    ``Code: N.`` prefix only repeats the errno and is dropped.
    """
    result = base._format_db_error(_mysql(errno, message))

    assert result == expected
    if canary:
        assert canary not in result


@pytest.mark.parametrize(
    ('errno', 'text'),
    [
        (1644, 'Upstream DB::Exception: Import aborted: While processing row 5'),
        (1062, "Duplicate entry 'DB::Exception: a here: b' for key 't.PRIMARY'"),
    ],
    ids=['signal', 'duplicate-entry'],
)
def test_mysql_text_that_only_mentions_db_exception_stays_whole(base, errno, text):
    """Only text that OPENS the way ClickHouse's does is taken for ClickHouse's.

    Constructed: MySQL text naming the phrase mid-sentence, with ClickHouse
    markers after it.
    """
    assert base._format_db_error(_mysql(errno, text)) == f'Error {errno}: {text}'


def test_mysql_branch_still_never_returns_the_sqlalchemy_tail(base):
    """The wrapper's ``[SQL: ...]`` / ``[parameters: ...]`` is still not what comes back."""
    exc = DBAPIError.instance(
        'SELECT * FROM t WHERE email = %s',
        ('ada@example.com',),
        _PyMySQLError(1644, 'Upload failed at position 3 of batch'),
        dbapi_base_err=Exception,
    )
    assert '[parameters:' in str(exc)

    result = base._format_db_error(exc)

    assert result == 'Error 1644: Upload failed at position 3 of batch'
    assert 'ada@example.com' not in result


def test_execute_reports_a_mysql_signal_message_whole():
    """The same message as the caller of the ``execute`` tool sees it."""
    message = _execute_error(_mysql(1644, 'Upload failed at position 3 of batch'))

    assert message == 'SQL execution failed: Error 1644: Upload failed at position 3 of batch'


# ---------------------------------------------------------------------------
# ClickHouse: a throwIf message is the caller's own text
#
# throwIf(cond, '<text>') raises with exactly <text>; ClickHouse appends
# ": while executing 'FUNCTION throwIf(...)'" (which repeats <text> as a
# literal) and then the stack trace.
# ---------------------------------------------------------------------------


def test_clickhouse_keeps_a_throwif_message_that_reads_like_a_scope_echo(base):
    """``SELECT throwIf(1, 'In scope SELECT secret')`` used to come back as ``Error 395: DB::Exception:``."""
    exc = _clickhouse(
        395,
        "DB::Exception: In scope SELECT secret: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
        "'In scope SELECT secret'_String :: 2) -> throwIf(1_UInt8, 'In scope SELECT secret'_String) UInt8 : 3'",
    )

    result = base._format_db_error(exc)

    # The runtime context repeats the text as a literal, so it reads like an
    # echo too; it is dropped whole rather than cut mid-literal.
    assert result == 'Error 395: DB::Exception: In scope SELECT secret'


def test_clickhouse_keeps_a_throwif_message_with_a_postgres_block_word(base):
    """``SELECT throwIf(1, 'line one\\nDETAIL: injected second line')`` used to stop at "line one".

    PostgreSQL's newline-anchored DETAIL marker has no business in ClickHouse
    text. Nothing in the runtime context is a ClickHouse marker, so it stays,
    exactly as it does for any other throwIf failure.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: line one\nDETAIL: injected second line: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
        "'line one\\nDETAIL: injected second line'_String :: 2) -> throwIf(1_UInt8, "
        "'line one\\nDETAIL: injected second line'_String) UInt8 : 3'",
    )

    assert base._format_db_error(exc) == (
        "Error 395: DB::Exception: line one\nDETAIL: injected second line: while executing 'FUNCTION "
        "throwIf(1_UInt8 :: 1, 'line one\\nDETAIL: injected second line'_String :: 2) -> throwIf(1_UInt8, "
        "'line one\\nDETAIL: injected second line'_String) UInt8 : 3'."
    )


@pytest.mark.parametrize(
    'text',
    ['Upload failed at position 3 of batch', 'Retry later. Stack trace: unavailable'],
    ids=['failed-at-position', 'stack-trace'],
)
def test_clickhouse_keeps_a_throwif_message_that_contains_a_tail_marker(base, text):
    """The ClickHouse analogue of the MySQL SIGNAL cases above.

    ``SELECT throwIf(1, $1)`` with ``$1`` bound to the text. The genuine stack
    trace is the LAST ``Stack trace:`` in the message, so a literal one inside
    the caller's text does not end it early.
    """
    exc = _clickhouse(
        395,
        f"DB::Exception: {text}: while executing 'FUNCTION throwIf(1_UInt8 :: 1, '{text}'_String :: 2) "
        f"-> throwIf(1_UInt8, '{text}'_String) UInt8 : 3'",
    )

    assert base._format_db_error(exc) == f'Error 395: DB::Exception: {text}'


def test_clickhouse_still_passes_a_throwif_runtime_context_through(base):
    """Unchanged: prose "in scope" is no echo, and the context after it stays.

    ``SELECT throwIf(1, 'not in scope for this trigger')``.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: not in scope for this trigger: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
        "'not in scope for this trigger'_String :: 2) -> throwIf(1_UInt8, 'not in scope for this trigger'_String) "
        "UInt8 : 3'",
    )

    assert base._format_db_error(exc) == (
        "Error 395: DB::Exception: not in scope for this trigger: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
        "'not in scope for this trigger'_String :: 2) -> throwIf(1_UInt8, 'not in scope for this trigger'_String) "
        "UInt8 : 3'."
    )


def test_clickhouse_keeps_a_throwif_message_evaluated_lazily_inside_if(base):
    """Keyed on code 395, so the context may name the ``if`` that ran ``throwIf``.

    ``SELECT if(number > 2, throwIf(1, 'Upload failed at position 3 of batch'),
    0) FROM numbers(5)``. With short-circuit evaluation the action reported is
    the ``if(...)`` whose branch called ``throwIf``, not ``throwIf`` itself,
    and ClickHouse truncates its result name with ``...`` mid-literal.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: Upload failed at position 3 of batch: while executing 'FUNCTION "
        "if(greater(__table1.number, 2_UInt8) :: 3, throwIf(1_UInt8, 'Upload failed at position 3 of batch'_String) "
        ':: 0, 0_UInt8 :: 4) -> if(greater(__table1.number, 2_UInt8), throwIf(1_UInt8, '
        "'Upload failed at position 3 of batch'_String... UInt8 : 1'",
    )

    assert base._format_db_error(exc) == 'Error 395: DB::Exception: Upload failed at position 3 of batch'


def test_clickhouse_does_not_split_a_throwif_message_at_its_own_words(base):
    """The context starts at ``: while executing 'FUNCTION ``, not at the caller's words.

    ``SELECT throwIf(1, 'step 1: while executing ''phase two'' failed at
    position 3')``. The caller's own "while executing" comes first; inside the
    context's literal ClickHouse escapes their quotes as ``\\'``.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: step 1: while executing 'phase two' failed at position 3: while executing 'FUNCTION "
        "throwIf(1_UInt8 :: 1, 'step 1: while executing \\'phase two\\' failed at position 3'_String :: 2) -> "
        "throwIf(1_UInt8, 'step 1: while executing \\'phase two\\' failed at position 3'_String) UInt8 : 3'",
    )

    assert base._format_db_error(exc) == (
        "Error 395: DB::Exception: step 1: while executing 'phase two' failed at position 3"
    )


def test_clickhouse_keeps_a_throwif_raised_inside_a_scalar_subquery(base):
    """A scalar subquery's ``throwIf`` is reported like a top-level one.

    ``SELECT (SELECT throwIf(1, 'boom')) AS v, $1 AS c`` with ``$1`` bound to
    ``QA_CANARY_SCALAR``. ClickHouse appends no ``In scope`` to it, before or
    after the runtime context, so the outer statement and its bound value never
    reach the message. The context holds no ClickHouse marker and stays.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: boom: while executing 'FUNCTION throwIf(1_UInt8 :: 1, 'boom'_String :: 2) -> "
        "throwIf(1_UInt8, 'boom'_String) UInt8 : 3'",
    )

    assert base._format_db_error(exc) == (
        "Error 395: DB::Exception: boom: while executing 'FUNCTION throwIf(1_UInt8 :: 1, 'boom'_String :: 2) -> "
        "throwIf(1_UInt8, 'boom'_String) UInt8 : 3'."
    )


def test_clickhouse_does_not_trust_a_throwif_context_spelled_into_an_echo(base):
    """Only code 395 is protected, so an alias cannot carry an echo past the markers.

    ``SELECT nope, 1 AS `: while executing 'FUNCTION throwIf(` FROM t WHERE
    qa_mark = $1`` fails with code 47, and the analyzer echoes the statement
    -- alias, bound value and all -- after ``in scope``.
    """
    exc = _clickhouse(
        47,
        'DB::Exception: Unknown expression identifier `nope` in scope SELECT nope, 1 AS '
        "`: while executing 'FUNCTION throwIf(` FROM t WHERE qa_mark = 'QA_CANARY_ALIAS'",
    )

    result = base._format_db_error(exc)

    assert result == 'Error 47: DB::Exception: Unknown expression identifier `nope`'
    assert 'QA_CANARY_ALIAS' not in result


def test_execute_reports_a_clickhouse_throwif_message_whole():
    """The same message as the caller of the ``execute`` tool sees it."""
    message = _execute_error(
        _clickhouse(
            395,
            "DB::Exception: In scope SELECT secret: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
            "'In scope SELECT secret'_String :: 2) -> throwIf(1_UInt8, 'In scope SELECT secret'_String) UInt8 : 3'",
        )
    )

    assert message == 'SQL execution failed: Error 395: DB::Exception: In scope SELECT secret'


# ---------------------------------------------------------------------------
# The new ClickHouse markers are as narrow as the old ones
#
# A driver nobody identified (sqlite3's bare args[0], here) still gets every
# dialect's markers as a backstop, so prose that merely shares a word with a
# new marker must survive there too.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'text',
    [
        'value is not allowed in query parameters',
        'aborted while processing batch 3',
        'temp table is not in scope x for this trigger',
        'Rule hit in query SELECT-list validation',
        'Import aborted: While processing row 5 of upload.csv',
        'Rejected: In query WITH clause not allowed',
        "constraint failed while processing: 'batch 7'",
        'Bad row here: 3',
    ],
    ids=[
        'in-query-prose',
        'while-processing-prose',
        'in-scope-name-prose',
        'keyword-not-followed-by-space',
        'capital-while-processing',
        'in-query-with',
        'while-processing-quote',
        'here',
    ],
)
def test_prose_sharing_a_word_with_a_clickhouse_marker_survives(base, text):
    """The backstop keeps the markers it had; the ClickHouse-only ones never reach it.

    Constructed texts, through the generic ``args[0]`` branch, which sqlite3
    and psycopg2 without ``diag`` reach and which cannot say who wrote the
    text. The last four used to be cut there by markers meant for ClickHouse's
    own text.
    """
    exc = DBAPIError.instance('SELECT 1', {}, _DriverError(text), dbapi_base_err=Exception)

    assert base._format_db_error(exc) == text
