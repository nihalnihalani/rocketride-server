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

    Constructed from the single-argument message above, for
    ``arrayMap((x, y) -> concat(x, y, $1, nope), ['a'], ['b'])``: ClickHouse's
    formatter prints a one-element lambda tuple as its bare element and any
    other as a parenthesised list.
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

    Constructed from the captured code-215 message, for the same aggregate
    error inside ``WITH x AS (SELECT order_id, count() ... WHERE qa_mark = $1
    GROUP BY customer) SELECT * FROM x``.
    """
    exc = _clickhouse(
        215,
        "DB::Exception: Column 'db.t.order_id' is not under aggregate function and not in GROUP BY keys. "
        "In query x AS (SELECT order_id, count() FROM t WHERE qa_mark = 'QA_CANARY_IN_QUERY_CTE' GROUP BY customer)",
    )

    result = base._format_db_error(exc)

    assert result == (
        "Error 215: DB::Exception: Column 'db.t.order_id' is not under aggregate function and not in GROUP BY keys."
    )
    assert 'QA_CANARY_IN_QUERY_CTE' not in result


def test_clickhouse_cuts_the_old_interpreters_while_processing_echo(base):
    """The pre-analyzer interpreter appends ``: While processing <expr>``.

    Constructed: the old interpreter runs with ``enable_analyzer = 0``, on
    servers before 24.3, and on some mutation paths, none of which the
    captured messages exercised. The expression it repeats carries the bound
    value like every other echo here.
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

    Constructed SIGNAL texts, one per marker this change adds; same shape as
    the captured ones above.
    """
    assert base._format_db_error(_mysql(1644, text)) == f'Error 1644: {text}'


def test_mysql_keeps_a_signal_message_that_contains_a_sqlalchemy_marker(base):
    """SQLAlchemy's tail is only ever in ``str()`` of its own exception, never in ``args``.

    Constructed SIGNAL text. On this branch the marker could only misfire.
    """
    text = 'Quota hit (Background on this error: see ops)'

    assert base._format_db_error(_mysql(1644, text)) == f'Error 1644: {text}'


@pytest.mark.parametrize(
    'fragment',
    ["'LINE 1: x'", "'Stack trace: x'", "'in scope SELECT'", "'[SQL: x]'"],
    ids=['line-n', 'stack-trace', 'in-scope', 'sqlalchemy-tail'],
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

    Constructed from the captured ``throwIf`` message shape. The genuine stack
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

    Constructed: with short-circuit evaluation the action reported is the
    ``if(...)`` whose branch called ``throwIf``, not ``throwIf`` itself.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: Upload failed at position 3 of batch: while executing 'FUNCTION if(greater(number, 2) :: 1, "
        "throwIf(1_UInt8, 'Upload failed at position 3 of batch'_String) :: 3, 0_UInt8 :: 2) -> if(...) UInt8 : 4'",
    )

    assert base._format_db_error(exc) == 'Error 395: DB::Exception: Upload failed at position 3 of batch'


def test_clickhouse_does_not_trust_a_throwif_context_spelled_into_an_echo(base):
    """Only code 395 is protected, so an alias cannot carry an echo past the markers.

    Constructed: ``SELECT nope, 1 AS `: while executing 'FUNCTION throwIf(`
    FROM t WHERE s = $1`` fails with code 47, and the analyzer echoes the
    statement -- alias, bound value and all -- after ``in scope``.
    """
    exc = _clickhouse(
        47,
        'DB::Exception: Unknown expression identifier `nope` in scope SELECT nope, 1 AS '
        "`: while executing 'FUNCTION throwIf(` FROM t WHERE s = 'QA_CANARY_ALIAS'",
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
    ],
    ids=['in-query-prose', 'while-processing-prose', 'in-scope-name-prose', 'keyword-not-followed-by-space'],
)
def test_prose_sharing_a_word_with_a_clickhouse_marker_survives(base, text):
    """Each marker needs the shape ClickHouse's formatter prints, not just the words.

    Constructed texts, through the generic ``args[0]`` branch.
    """
    exc = DBAPIError.instance('SELECT 1', {}, _DriverError(text), dbapi_base_err=Exception)

    assert base._format_db_error(exc) == text
