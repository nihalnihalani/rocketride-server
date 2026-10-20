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

The sections added for the older-server and input-echo fixes (from "ClickHouse
text in every shape a driver hands over" on) take their payloads from the
``_LIVE`` table instead: ClickHouse 23.8.16.16 and 25.8.33.6 and MySQL 8.4.11,
each entry naming the capture it was copied from. Anything else in those
sections says it is constructed or replayed (a live payload fed through a
different exception shape).

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
import re

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


class _ClickHouseConnectError(Exception):
    """Stand-in for clickhouse-connect 1.11.0's ``DatabaseError`` (HTTP).

    The whole wrapper is one line in ``args[0]``, and the error also carries the
    server's code as an integer ``.code`` -- there is no ``.message``.
    """

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def _dbapi(server_exception):
    """What ``clickhouse_driver.dbapi`` raises, wrapped the way SQLAlchemy wraps it."""
    return DBAPIError.instance('SELECT 1', {}, _ClickHouseDbapiError(server_exception), dbapi_base_err=Exception)


def _server(code, message):
    """The driver's own exception for a live ``.message``, trace appended."""
    return _ClickHouseServerException(code, message + _CLICKHOUSE_STACK_TRACE)


def _with_trace(text):
    """A live ``str()`` of the driver's exception, which also ends in the trace."""
    return text + _CLICKHOUSE_STACK_TRACE


def _driver_error(text):
    """An exception whose ``args`` are ``(text,)`` and that has no ``.code`` / ``.message`` / ``.orig``."""
    return DBAPIError.instance('SELECT 1', {}, _DriverError(text), dbapi_base_err=Exception)


# Payloads captured from live servers: ClickHouse 23.8.16.16 and 25.8.33.6 (through clickhouse-driver 0.2.9,
# clickhouse-sqlalchemy 0.3.2, PyMySQL 1.2.3 and clickhouse-connect 1.11.0) and MySQL 8.4.11 (PyMySQL 1.2.3),
# copied byte for byte; only the stack trace after ``. Stack trace:`` is dropped (the stripper cuts at its
# header, so the frames are irrelevant). The comment on each entry names the capture it came from, as
# ``<server>__<route>__<statement>`` in the evidence of the QA run for PR #2713 (kept outside this repository),
# or a probe of the same run; the test that uses the entry names the statement. Keys read
# ``<server>.<statement>.<route>``. QA_CANARY_* values are bound into LATER rows, which the formatter must not
# return.
_LIVE = {
    # repro/captures/ch23__driver-native__c27_values_before.json .error.message
    'ch23.c27.native': (
        "DB::ParsingException. DB::ParsingException: Cannot parse input: expected '(' before: 'ON DUPLICA"
        "TE KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlo"
        'ckInputFormat'
    ),
    # repro/captures/ch23__driver-dbapi__c27_values_before.json .error.str
    'ch23.c27.dbapi_str': (
        "Code: 27.\nDB::ParsingException. DB::ParsingException: Cannot parse input: expected '(' before: '"
        "ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing"
        ' ValuesBlockInputFormat'
    ),
    # repro/captures/ch23__sqla-native__c27_values_before.json .error.orig... DatabaseException str
    'ch23.c27.sqla_str': (
        'Orig exception: Code: 27.\nDB::ParsingException. DB::ParsingException: Cannot parse input: expect'
        "ed '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1:"
        ' While executing ValuesBlockInputFormat'
    ),
    # repro/captures/ch23__clickhouse-connect__c27_values_before.json .error.args[0]
    'ch23.c27.connect': (
        'Received ClickHouse exception, code: 27, server response: Code: 27. DB::ParsingException: Cannot'
        " parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANAR"
        "Y_B2\\')':  at row 1: While executing ValuesBlockInputFormat. (CANNOT_PARSE_INPUT_ASSERTION_FAILE"
        'D) (version 23.8.16.16 (official build)) (for url http://127.0.0.1:28123)'
    ),
    # repro/captures/ch23__mysql-wire__c27_values_before.json .error.args
    'ch23.c27.mysql': (
        27,
        (
            "Code: 27. DB::ParsingException: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDAT"
            "E s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlockInputForma"
            't. (CANNOT_PARSE_INPUT_ASSERTION_FAILED) (version 23.8.16.16 (official build))'
        ),
    ),
    # repro/captures/ch23__driver-native__c53_values_null_strict.json .error.message
    'ch23.c53.native': (
        "DB::Exception: Cannot insert NULL value into a column of type 'UInt32' at: NULL, 'QA_CANARY_N3')"
        ", (3, 'QA_CANARY_N4'): While executing ValuesBlockInputFormat"
    ),
    # repro/captures/ch23__mysql-wire__c53_values_null_strict.json .error.args
    'ch23.c53.mysql': (
        53,
        (
            "Code: 53. DB::Exception: Cannot insert NULL value into a column of type 'UInt32' at: NULL, 'QA_C"
            "ANARY_N3'), (3, 'QA_CANARY_N4'): While executing ValuesBlockInputFormat. (TYPE_MISMATCH) (versio"
            'n 23.8.16.16 (official build))'
        ),
    ),
    # repro/captures/ch23__clickhouse-connect__c53_values_null_strict.json .error.args[0]
    'ch23.c53.connect': (
        'Received ClickHouse exception, code: 53, server response: Code: 53. DB::Exception: Cannot insert'
        " NULL value into a column of type 'UInt32' at: NULL, 'QA_CANARY_N3'), (3, 'QA_CANARY_N4'): While"
        ' executing ValuesBlockInputFormat. (TYPE_MISMATCH) (version 23.8.16.16 (official build)) (for ur'
        'l http://127.0.0.1:28123)'
    ),
    # repro/captures/ch23__driver-native__csv_row_parse.json .error.message
    'ch23.csv.native': (
        "DB::ParsingException. DB::ParsingException: Cannot parse input: expected ',' before: 'abc,\"QA_CA"
        'NARY_C2"\\n3,"QA_CANARY_C3"\\n\': \nRow 1:\nColumn 0,   name: id, type: UInt32, parsed text: "1"\nColu'
        'mn 1,   name: s,  type: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C1<DOUBLE QUOTE>"\n\nRow 2:\n'
        'Column 0,   name: id, type: UInt32, ERROR: text "abc,<DOUBLE QUOTE>QA_CA" is not like UInt32\n\n: '
        'While executing ParallelParsingBlockInputFormat: (at row 2)\n'
    ),
    # repro/captures/ch23__driver-native__tsv_row_parse.json .error.message
    'ch23.tsv.native': (
        "DB::ParsingException. DB::ParsingException: Cannot parse input: expected '\\t' before: 'xyz\\tQA_C"
        'ANARY_T2\\n3\\tQA_CANARY_T3\\n\': \nRow 1:\nColumn 0,   name: id, type: UInt32, parsed text: "1"\nColum'
        'n 1,   name: s,  type: String, parsed text: "QA_CANARY_T1"\n\nRow 2:\nColumn 0,   name: id, type: U'
        'Int32, ERROR: text "xyz<TAB>QA_CAN" is not like UInt32\n\n: While executing ParallelParsingBlockIn'
        'putFormat: (at row 2)\n'
    ),
    # repro/captures/ch23__driver-native__c62_syntax.json .error.message
    'ch23.syntax.native': (
        "DB::Exception: Syntax error: failed at position 1 ('SELEC'): SELEC id FROM qa_rel.t WHERE s = 'Q"
        "A_CANARY_Y1'. Expected one of: Query, Query with output, EXPLAIN, SELECT query, possibly with UN"
        'ION, list of union elements, SELECT query, subquery, possibly with UNION, SELECT subquery, SELEC'
        'T query, WITH, FROM, SELECT, SHOW CREATE QUOTA query, SHOW CREATE, SHOW [FULL] [TEMPORARY] TABLE'
        "S|DATABASES|CLUSTERS|CLUSTER 'name' [[NOT] [I]LIKE 'str'] [LIMIT expr], SHOW, SHOW COLUMNS query"
        ', SHOW ENGINES query, SHOW ENGINES, SHOW INDEXES query, EXISTS or SHOW CREATE query, EXISTS, DES'
        'CRIBE FILESYSTEM CACHE query, DESCRIBE, DESC, DESCRIBE query, SHOW PROCESSLIST query, SHOW PROCE'
        'SSLIST, CREATE TABLE or ATTACH TABLE query, CREATE, ATTACH, REPLACE, CREATE DATABASE query, CREA'
        'TE VIEW query, CREATE DICTIONARY, CREATE LIVE VIEW query, CREATE WINDOW VIEW query, ALTER query,'
        ' ALTER TABLE, ALTER LIVE VIEW, ALTER DATABASE, RENAME query, RENAME TABLE, EXCHANGE TABLES, RENA'
        'ME DICTIONARY, EXCHANGE DICTIONARIES, RENAME DATABASE, DROP query, DROP, DETACH, TRUNCATE, UNDRO'
        'P query, UNDROP, CHECK TABLE, KILL QUERY query, KILL, OPTIMIZE query, OPTIMIZE TABLE, WATCH quer'
        'y, WATCH, SHOW ACCESS query, SHOW ACCESS, ShowAccessEntitiesQuery, SHOW GRANTS query, SHOW GRANT'
        'S, SHOW PRIVILEGES query, SHOW PRIVILEGES, INSERT query, INSERT INTO, USE query, USE, SET ROLE o'
        'r SET DEFAULT ROLE query, SET ROLE DEFAULT, SET ROLE, SET DEFAULT ROLE, SET query, SET, SYSTEM q'
        'uery, SYSTEM, CREATE USER or ALTER USER query, ALTER USER, CREATE USER, CREATE ROLE or ALTER ROL'
        'E query, ALTER ROLE, CREATE ROLE, CREATE QUOTA or ALTER QUOTA query, ALTER QUOTA, CREATE QUOTA, '
        'CREATE ROW POLICY or ALTER ROW POLICY query, ALTER POLICY, ALTER ROW POLICY, CREATE POLICY, CREA'
        'TE ROW POLICY, CREATE SETTINGS PROFILE or ALTER SETTINGS PROFILE query, ALTER SETTINGS PROFILE, '
        'ALTER PROFILE, CREATE SETTINGS PROFILE, CREATE PROFILE, CREATE FUNCTION query, DROP FUNCTION que'
        'ry, CREATE NAMED COLLECTION, DROP NAMED COLLECTION query, Alter NAMED COLLECTION query, ALTER, C'
        'REATE INDEX query, DROP INDEX query, DROP access entity query, MOVE access entity query, MOVE, G'
        'RANT or REVOKE query, REVOKE, GRANT, EXTERNAL DDL query, EXTERNAL DDL FROM, TCL query, BEGIN TRA'
        'NSACTION, COMMIT, ROLLBACK, SET TRANSACTION SNAPSHOT, Delete query, DELETE, BACKUP or RESTORE qu'
        'ery, BACKUP, RESTORE'
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_nested_parens native
    'ch23.deduce.native': (
        "DB::Exception: Cannot deduce template of expression: lower((('QA_CANARY_D3')))): While executing"
        ' ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_nested_parens mysql
    'ch23.deduce.mysql': (
        62,
        (
            "Code: 62. DB::Exception: Cannot deduce template of expression: lower((('QA_CANARY_D3')))): While"
            ' executing ValuesBlockInputFormat. (SYNTAX_ERROR) (version 23.8.16.16 (official build))'
        ),
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_paren native
    'ch23.deduce_paren.native': (
        'DB::Exception: Cannot deduce template of expression: (1 + 1), : While executing ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/a62.json c36_not_constant_str native
    'ch23.notconst.native': (
        'DB::Exception: Element of set in IN, VALUES, or LIMIT, or aggregate function parameter, or a tab'
        "le function argument is not a constant expression (result column not found): arrayJoin(['QA_CANA"
        "RY_D7']): While executing ValuesBlockInputFormat"
    ),
    # team/formatter_engineer/probes/a62.json c36_not_constant_str http
    'ch23.notconst.connect': (
        'Received ClickHouse exception, code: 36, server response: Code: 36. DB::Exception: Element of se'
        't in IN, VALUES, or LIMIT, or aggregate function parameter, or a table function argument is not '
        "a constant expression (result column not found): arrayJoin(['QA_CANARY_D7']): While executing Va"
        'luesBlockInputFormat. (BAD_ARGUMENTS) (version 23.8.16.16 (official build)) (for url http://127.'
        '0.0.1:28123)'
    ),
    # team/formatter_engineer/probes/b.json b_csv_extra_col native
    'ch23.row117.native': (
        'DB::Exception: Expected end of line: (at row 2)\n: \nRow 1:\nColumn 0,   name: id, type: UInt32, pa'
        'rsed text: "1"\nColumn 1,   name: s,  type: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C1<DOUB'
        'LE QUOTE>"\n\nRow 2:\nColumn 0,   name: id, type: UInt32, parsed text: "2"\nColumn 1,   name: s,  ty'
        'pe: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C2<DOUBLE QUOTE>"\nERROR: There is no line feed'
        '. "9" found instead.\n It\'s like your file has more columns than expected.\nAnd if your file has t'
        'he right number of columns, maybe it has an unquoted string value with a comma.\n\n: While executi'
        'ng ParallelParsingBlockInputFormat'
    ),
    # team/formatter_engineer/probes/b.json b_csv_negative native
    'ch23.row72.native': (
        "DB::ParsingException. DB::ParsingException: Unsigned type must not contain '-' symbol: \nRow 1:\nC"
        'olumn 0,   name: id, type: UInt32, parsed text: "1"\nColumn 1,   name: s,  type: String, parsed t'
        'ext: "<DOUBLE QUOTE>QA_CANARY_C1<DOUBLE QUOTE>"\n\nRow 2:\nColumn 0,   name: id, type: UInt32, ERRO'
        'R: text "-5,<DOUBLE QUOTE>QA_CAN" is not like UInt32\n\n: While executing CSVRowInputFormat: (at r'
        'ow 2)\n'
    ),
    # team/formatter_engineer/probes/s.json throwif_empty native
    'ch23.throwif_empty.native': "DB::Exception: while executing 'FUNCTION throwIf(1 :: 0, '' :: 1) -> throwIf(1, '') UInt8 : 2'",
    # repro/captures/ch25__driver-native__c27_values_before.json .error.message
    'ch25.c27.native': (
        "DB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY"
        "_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlockInputFormat"
    ),
    # repro/captures/ch25__driver-dbapi__c27_values_before.json .error.str
    'ch25.c27.dbapi_str': (
        "Code: 27.\nDB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\"
        "'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlockInputFormat"
    ),
    # repro/captures/ch25__sqla-native__c27_values_before.json .error.orig... DatabaseException str
    'ch25.c27.sqla_str': (
        "Orig exception: Code: 27.\nDB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE "
        "KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlockI"
        'nputFormat'
    ),
    # repro/captures/ch25__clickhouse-connect__c27_values_before.json .error.args[0]
    'ch25.c27.connect': (
        'Received ClickHouse exception, code: 27, server response: Code: 27. DB::Exception: Cannot parse '
        "input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')"
        "':  at row 1: While executing ValuesBlockInputFormat. (CANNOT_PARSE_INPUT_ASSERTION_FAILED) (ver"
        'sion 25.8.33.6 (official build)) (for url http://127.0.0.1:38123)'
    ),
    # repro/captures/ch25__mysql-wire__c27_values_before.json .error.args
    'ch25.c27.mysql': (
        27,
        (
            "Code: 27. DB::Exception: Cannot parse input: expected '(' before: 'ON DUPLICATE KEY UPDATE s = \\"
            "'QA_CANARY_B1\\', (3, \\'QA_CANARY_B2\\')':  at row 1: While executing ValuesBlockInputFormat. (CAN"
            'NOT_PARSE_INPUT_ASSERTION_FAILED) (version 25.8.33.6 (official build))'
        ),
    ),
    # repro/captures/ch25__driver-native__c53_values_null_strict.json .error.message
    'ch25.c53.native': (
        "DB::Exception: Cannot insert NULL value into a column of type 'UInt32' at: NULL, 'QA_CANARY_N3')"
        ", (3, 'QA_CANARY_N4'): While executing ValuesBlockInputFormat"
    ),
    # repro/captures/ch25__mysql-wire__c53_values_null_strict.json .error.args
    'ch25.c53.mysql': (
        53,
        (
            "Code: 53. DB::Exception: Cannot insert NULL value into a column of type 'UInt32' at: NULL, 'QA_C"
            "ANARY_N3'), (3, 'QA_CANARY_N4'): While executing ValuesBlockInputFormat. (TYPE_MISMATCH) (versio"
            'n 25.8.33.6 (official build))'
        ),
    ),
    # repro/captures/ch25__clickhouse-connect__c53_values_null_strict.json .error.args[0]
    'ch25.c53.connect': (
        'Received ClickHouse exception, code: 53, server response: Code: 53. DB::Exception: Cannot insert'
        " NULL value into a column of type 'UInt32' at: NULL, 'QA_CANARY_N3'), (3, 'QA_CANARY_N4'): While"
        ' executing ValuesBlockInputFormat. (TYPE_MISMATCH) (version 25.8.33.6 (official build)) (for url'
        ' http://127.0.0.1:38123)'
    ),
    # repro/captures/ch25__driver-native__csv_row_parse.json .error.message
    'ch25.csv.native': (
        'DB::Exception: Cannot parse input: expected \',\' before: \'abc,"QA_CANARY_C2"\\n3,"QA_CANARY_C3"\\n\''
        ': (at row 2)\n: \nRow 1:\nColumn 0,   name: id, type: UInt32, parsed text: "1"\nColumn 1,   name: s,'
        '  type: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C1<DOUBLE QUOTE>"\n\nRow 2:\nColumn 0,   name'
        ': id, type: UInt32, ERROR: text "abc,<DOUBLE QUOTE>QA_CA" is not like UInt32\n\n: While executing '
        'ParallelParsingBlockInputFormat'
    ),
    # repro/captures/ch25__driver-native__tsv_row_parse.json .error.message
    'ch25.tsv.native': (
        "DB::Exception: Cannot parse input: expected '\\t' before: 'xyz\\tQA_CANARY_T2\\n3\\tQA_CANARY_T3\\n':"
        ' (at row 2)\n: \nRow 1:\nColumn 0,   name: id, type: UInt32, parsed text: "1"\nColumn 1,   name: s, '
        ' type: String, parsed text: "QA_CANARY_T1"\n\nRow 2:\nColumn 0,   name: id, type: UInt32, ERROR: te'
        'xt "xyz<TAB>QA_CAN" is not like UInt32\n\n: While executing ParallelParsingBlockInputFormat'
    ),
    # repro/captures/ch25__driver-native__c62_syntax.json .error.message
    'ch25.syntax.native': (
        "DB::Exception: Syntax error: failed at position 1 (SELEC): SELEC id FROM qa_rel.t WHERE s = 'QA_"
        "CANARY_Y1'. Expected one of: Query, Query with output, EXPLAIN, EXPLAIN, SELECT query, possibly "
        'with UNION, list of union elements, SELECT query, subquery, possibly with UNION, SELECT subquery'
        ', SELECT query, WITH, FROM, SELECT, SHOW CREATE QUOTA query, SHOW CREATE, SHOW [FULL] [TEMPORARY'
        "] TABLES|DATABASES|CLUSTERS|CLUSTER|MERGES 'name' [[NOT] [I]LIKE 'str'] [LIMIT expr], SHOW, SHOW"
        ' COLUMNS query, SHOW ENGINES query, SHOW ENGINES, SHOW FUNCTIONS query, SHOW FUNCTIONS, SHOW IND'
        'EXES query, SHOW SETTING query, SHOW SETTING, EXISTS or SHOW CREATE query, EXISTS, DESCRIBE FILE'
        'SYSTEM CACHE query, DESCRIBE, DESC, DESCRIBE query, SHOW PROCESSLIST query, SHOW PROCESSLIST, CR'
        'EATE TABLE or ATTACH TABLE query, CREATE, ATTACH, REPLACE, CREATE DATABASE query, CREATE VIEW qu'
        'ery, CREATE DICTIONARY, CREATE LIVE VIEW query, CREATE WINDOW VIEW query, ALTER query, ALTER TAB'
        'LE, ALTER TEMPORARY TABLE, ALTER DATABASE, RENAME query, RENAME DATABASE, RENAME TABLE, EXCHANGE'
        ' TABLES, RENAME DICTIONARY, EXCHANGE DICTIONARIES, RENAME, DROP query, DROP, DETACH, TRUNCATE, U'
        'NDROP query, UNDROP, CHECK ALL TABLES, CHECK TABLE, KILL QUERY query, KILL, OPTIMIZE query, OPTI'
        'MIZE TABLE, WATCH query, WATCH, SHOW ACCESS query, SHOW ACCESS, ShowAccessEntitiesQuery, SHOW GR'
        'ANTS query, SHOW GRANTS, SHOW PRIVILEGES query, SHOW PRIVILEGES, BACKUP or RESTORE query, BACKUP'
        ', RESTORE, INSERT query, INSERT INTO, USE query, USE, SET ROLE or SET DEFAULT ROLE query, SET RO'
        'LE DEFAULT, SET ROLE, SET DEFAULT ROLE, SET query, SET, SYSTEM query, SYSTEM, CREATE USER or ALT'
        'ER USER query, ALTER USER, CREATE USER, CREATE ROLE or ALTER ROLE query, ALTER ROLE, CREATE ROLE'
        ', CREATE QUOTA or ALTER QUOTA query, ALTER QUOTA, CREATE QUOTA, CREATE ROW POLICY or ALTER ROW P'
        'OLICY query, ALTER POLICY, ALTER ROW POLICY, CREATE POLICY, CREATE ROW POLICY, CREATE SETTINGS P'
        'ROFILE or ALTER SETTINGS PROFILE query, ALTER SETTINGS PROFILE, ALTER PROFILE, CREATE SETTINGS P'
        'ROFILE, CREATE PROFILE, CREATE FUNCTION query, DROP FUNCTION query, CREATE WORKLOAD query, DROP '
        'WORKLOAD query, CREATE RESOURCE query, DROP RESOURCE query, CREATE NAMED COLLECTION, DROP NAMED '
        'COLLECTION query, Alter NAMED COLLECTION query, ALTER, CREATE INDEX query, DROP INDEX query, DRO'
        'P access entity query, MOVE access entity query, MOVE, GRANT or REVOKE query, REVOKE, GRANT, CHE'
        'CK GRANT, CHECK GRANT, TCL query, BEGIN TRANSACTION, START TRANSACTION, COMMIT, ROLLBACK, SET TR'
        'ANSACTION SNAPSHOT, Delete query, DELETE, Update query, UPDATE, COPY query, COPY'
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_nested_parens native
    'ch25.deduce.native': (
        "DB::Exception: Cannot deduce template of expression: lower((('QA_CANARY_D3')))): While executing"
        ' ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_nested_parens mysql
    'ch25.deduce.mysql': (
        62,
        (
            "Code: 62. DB::Exception: Cannot deduce template of expression: lower((('QA_CANARY_D3')))): While"
            ' executing ValuesBlockInputFormat. (SYNTAX_ERROR) (version 25.8.33.6 (official build))'
        ),
    ),
    # team/formatter_engineer/probes/a62.json c62_deduce_paren native
    'ch25.deduce_paren.native': (
        'DB::Exception: Cannot deduce template of expression: (1 + 1), : While executing ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/a62.json c36_not_constant_str native
    'ch25.notconst.native': (
        'DB::Exception: Element of set in IN, VALUES, or LIMIT, or aggregate function parameter, or a tab'
        "le function argument is not a constant expression (result column not found): arrayJoin(['QA_CANA"
        "RY_D7']): While executing ValuesBlockInputFormat"
    ),
    # team/formatter_engineer/probes/a62.json c36_not_constant_str http
    'ch25.notconst.connect': (
        'Received ClickHouse exception, code: 36, server response: Code: 36. DB::Exception: Element of se'
        't in IN, VALUES, or LIMIT, or aggregate function parameter, or a table function argument is not '
        "a constant expression (result column not found): arrayJoin(['QA_CANARY_D7']): While executing Va"
        'luesBlockInputFormat. (BAD_ARGUMENTS) (version 25.8.33.6 (official build)) (for url http://127.0'
        '.0.1:38123)'
    ),
    # team/formatter_engineer/probes/b.json b_csv_extra_col native
    'ch25.row117.native': (
        'DB::Exception: Expected end of line: (at row 2)\n: \nRow 1:\nColumn 0,   name: id, type: UInt32, pa'
        'rsed text: "1"\nColumn 1,   name: s,  type: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C1<DOUB'
        'LE QUOTE>"\n\nRow 2:\nColumn 0,   name: id, type: UInt32, parsed text: "2"\nColumn 1,   name: s,  ty'
        'pe: String, parsed text: "<DOUBLE QUOTE>QA_CANARY_C2<DOUBLE QUOTE>"\nERROR: There is no line feed'
        '. "9" found instead.\n It\'s like your file has more columns than expected.\nAnd if your file has t'
        'he right number of columns, maybe it has an unquoted string value with a comma.\n\n: While executi'
        'ng ParallelParsingBlockInputFormat'
    ),
    # team/formatter_engineer/probes/b.json b_csv_negative native
    'ch25.row72.native': (
        "DB::Exception: Unsigned type must not contain '-' symbol: (at row 2)\n: \nRow 1:\nColumn 0,   name:"
        ' id, type: UInt32, parsed text: "1"\nColumn 1,   name: s,  type: String, parsed text: "<DOUBLE QU'
        'OTE>QA_CANARY_C1<DOUBLE QUOTE>"\n\nRow 2:\nColumn 0,   name: id, type: UInt32, ERROR: text "-5,<DOU'
        'BLE QUOTE>QA_CAN" is not like UInt32\n\n: While executing CSVRowInputFormat'
    ),
    # team/formatter_engineer/probes/s.json throwif_empty native
    'ch25.throwif_empty.native': (
        "DB::Exception: while executing 'FUNCTION throwIf(1_UInt8 :: 1, ''_String :: 2) -> throwIf(1_UInt"
        "8, ''_String) UInt8 : 3'"
    ),
    # team/formatter_engineer/probes/s.json scope_literal_eq native
    'ch25.scope_literal.native': (
        "DB::Exception: Unknown expression or function identifier `nope` in scope 'QA_CANARY_S3' = nope: "
        'While executing ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/s.json scope_tuple_elem native
    'ch25.scope_tuple.native': (
        "DB::Exception: Unknown expression or function identifier `nope` in scope ('QA_CANARY_S9', nope)."
        '1: While executing ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/s.json scope_array_elem native
    'ch25.scope_array.native': (
        "DB::Exception: Unknown expression or function identifier `nope` in scope ['QA_CANARY_A1', nope]["
        '1]: While executing ValuesBlockInputFormat'
    ),
    # team/formatter_engineer/probes/s.json scope_in_fn native (code 36)
    'ch23.scope_in_fn.native': (
        'DB::Exception: Element of set in IN, VALUES, or LIMIT, or aggregate function parameter, or a tab'
        "le function argument is not a constant expression (result column not found): toString(in('QA_CAN"
        "ARY_SB', nope)): While executing ValuesBlockInputFormat"
    ),
    # repro/captures/mysql84__pymysql__signal_db_exception_text.json
    'mysql84.signal_db_exception': (
        1644,
        'DB::Exception: tenant QA_APP_T1 rejected. Upload failed at position 3 of batch',
    ),
    # repro/captures/mysql84__pymysql__signal_code_prefix_text.json
    'mysql84.signal_code_prefix': (1644, "Code: 1644. DB::Exception: app text before: 'x' kept"),
    # team/formatter_engineer/probes/mysql_signal.json signal_multiline_db
    'mysql84.signal_multiline_db': (1644, 'Order rejected\nDB::Exception: app text here: kept'),
    # team/formatter_engineer/probes/mysql_signal.json signal_class_prefix
    'mysql84.signal_class_prefix': (1644, 'DB::ParsingException. DB::ParsingException: app text here: kept'),
    # team/formatter_engineer/probes/mysql_signal.json signal_forged_code_same_errno
    'mysql84.signal_forged_code_same_errno': (47, "Code: 47. DB::Exception: app text before: 'x' kept"),
    # team/formatter_engineer/probes/mysql_signal.json signal_forged_code_other_errno
    'mysql84.signal_forged_code_other_errno': (1644, "Code: 47. DB::Exception: app text before: 'x' kept"),
}


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
    """``SELEC <fragment> FROM qa_my_customers`` -> 1064, quoting the rest of the statement from where it stopped.

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


# ---------------------------------------------------------------------------
# ClickHouse text in every shape a driver hands over
#
# The formatter used to recognise ClickHouse's text only when it began with
# ``DB::<Name>Exception:``. clickhouse-driver puts the class name in front of
# the message of a subclass (``DB::ParsingException. DB::ParsingException:
# ...``, 23.8's parse errors), ``str()`` of its exception opens with
# ``Code: N.`` and a newline, and clickhouse-connect wraps the text in one
# line, so the ``before: '`` echo of the rows that follow a parse error came
# back with every later bound value.
# ---------------------------------------------------------------------------


def _c27_routes(server):
    """One exception per route for the same live statement, as that route's driver raises it.

    ``INSERT INTO qa_rel.t (id, s) VALUES (1, 'a') ON DUPLICATE KEY UPDATE s = 'QA_CANARY_B1', (3, 'QA_CANARY_B2')``
    """
    return {
        # The db_clickhouse node's connector: clickhouse-sqlalchemy's DatabaseException around the driver's.
        'sqla-native': _clickhouse(27, _LIVE[f'{server}.c27.native']),
        'driver-dbapi': _dbapi(_server(27, _LIVE[f'{server}.c27.native'])),
        # Replayed: ``str()`` of those exceptions through the generic ``args[0]`` shape.
        'str-of-server-exception': _driver_error(_with_trace(_LIVE[f'{server}.c27.dbapi_str'])),
        'str-of-database-exception': _driver_error(_with_trace(_LIVE[f'{server}.c27.sqla_str'])),
        'clickhouse-connect': _ClickHouseConnectError(_LIVE[f'{server}.c27.connect'], 27),
        'mysql-wire': _mysql(*_LIVE[f'{server}.c27.mysql']),
    }


@pytest.mark.parametrize(
    ('server', 'driver_text', 'class_name'),
    [
        ('ch23', 'DB::ParsingException. DB::ParsingException', 'DB::ParsingException'),
        ('ch25', 'DB::Exception', 'DB::Exception'),
    ],
)
def test_clickhouse_values_before_echo_is_cut_on_every_route(base, server, driver_text, class_name):
    """The review's blocker: 23.8's ``DB::ParsingException. DB::ParsingException:`` and its ``str()`` / HTTP shapes.

    One statement, every route. On 23.8 the driver's ``.message`` opens with its
    own repeated class name, so the text fell through to the backstop, which has
    no ``before: '`` marker, and every later row came back. The three routes
    that hand over a code and a message (the node's connector, the dbapi layer
    and ClickHouse's MySQL wire) return the same sentence. The ``str()`` and
    HTTP shapes keep the form they arrived in and lose the same echo.
    """
    sentence = "Cannot parse input: expected '('"
    structured = f'Error 27: {class_name}: {sentence}'
    expected = {
        'sqla-native': structured,
        'driver-dbapi': structured,
        'mysql-wire': structured,
        'str-of-server-exception': f'Code: 27.\n{driver_text}: {sentence}',
        'str-of-database-exception': f'Orig exception: Code: 27.\n{driver_text}: {sentence}',
        'clickhouse-connect': f'Received ClickHouse exception, code: 27, server response: Code: 27. {class_name}: {sentence}',
    }

    results = {route: base._format_db_error(exc) for route, exc in _c27_routes(server).items()}

    assert results == expected
    for result in results.values():
        assert 'QA_CANARY_B1' not in result
        assert 'QA_CANARY_B2' not in result


def test_clickhouse_text_from_an_older_server_is_still_recognised(base):
    """Older servers name the parse error's class ``DB::ParsingException:``.

    Live: the ``.message`` clickhouse-driver builds for it, repeated class name
    included (it used to be a hand-written ``DB::ParsingException: ...`` that
    the driver never produces), and the same statement over ClickHouse's MySQL
    wire, both from 23.8.16.16.
    """
    native = base._format_db_error(_clickhouse(27, _LIVE['ch23.c27.native']))
    mysql_wire = base._format_db_error(_mysql(*_LIVE['ch23.c27.mysql']))

    assert native == "Error 27: DB::ParsingException: Cannot parse input: expected '('"
    assert mysql_wire == native
    for result in (native, mysql_wire):
        assert 'QA_CANARY_B1' not in result
        assert 'QA_CANARY_B2' not in result


def test_clickhouse_message_without_the_drivers_repeated_class_name_is_still_recognised(base):
    """Constructed: ``DB::ParsingException: ...`` with no driver prefix, as an earlier test of this module wrote it.

    The driver does not produce this shape (see above); it stays covered because the classifier must not
    require the prefix.
    """
    exc = _clickhouse(
        27,
        "DB::ParsingException: Cannot parse input: expected '(' before: "
        "'ON DUPLICATE KEY UPDATE s = \\'QA_CANARY_OLDER\\'':  at row 1: While executing ValuesBlockInputFormat",
    )

    result = base._format_db_error(exc)

    assert result == "Error 27: DB::ParsingException: Cannot parse input: expected '('"
    assert 'QA_CANARY_OLDER' not in result


def test_clickhouse_connect_error_without_a_matching_second_code_is_not_taken_for_clickhouses(base):
    """Constructed: the wrapper is recognised only when both codes in it are the same number.

    Text that merely looks like clickhouse-connect's wrapper keeps the backstop alone, which has no ``before: '``
    marker.
    """
    text = "Received ClickHouse exception, code: 27, server response: Code: 28. DB::Exception: x before: 'SECRET_BIND'"

    assert base._format_db_error(_ClickHouseConnectError(text, 27)) == text


@pytest.mark.parametrize(
    'text',
    [
        # ClickHouse text on a LATER line is not ClickHouse's envelope: only the shapes seen live open the text.
        'Order rejected\nDB::Exception: app text here: kept',
        'ERROR:  bad row\nDB::Exception: relayed by app\nDETAIL:  Key (email)=(a@b.c) already exists.',
        # A mid-line mention.
        "Retry: Code: 47. DB::Exception: app text before: 'x' kept",
        'Orig exception: relayed: Code: 47.\nDB::Exception: app text here: kept',
    ],
    ids=['later-line', 'later-line-with-detail', 'mid-line', 'wrapper-not-at-the-start'],
)
def test_text_that_only_contains_clickhouses_class_on_another_line_is_not_cut_with_its_markers(base, text):
    """Constructed: no ClickHouse marker (`` here: ``, `` before: '``) reaches text that is not opened by a known shape.

    The first three were written to come back as the backstop alone cuts them
    (the second at its ``DETAIL:`` block), whole otherwise.
    """
    result = base._format_db_error(_driver_error(text))

    assert result == text.split('\nDETAIL:')[0]


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        # Constructed after the shapes in E/team/devils_advocate/da_monotonic_check.py.
        (
            "Code: 47.\nDB::Exception: Missing columns: 'x' [SQL: SELECT 1 WHERE s = 'QA_CANARY_SQL']",
            "Code: 47.\nDB::Exception: Missing columns: 'x'",
        ),
        (
            "Orig exception: Code: 47.\nDB::Exception: Missing columns: 'x'\n[parameters: {'p1': 'QA_CANARY_PARAMS'}]",
            "Orig exception: Code: 47.\nDB::Exception: Missing columns: 'x'",
        ),
        (
            'Code: 47.\nDB::Exception: Unique violation\nDETAIL:  Key (email)=(QA_CANARY_PG) already exists.',
            'Code: 47.\nDB::Exception: Unique violation',
        ),
        (
            "Code: 47.\nDB::Exception: Cannot parse input before: 'QA_CANARY_B' [SQL: SELECT 1]",
            'Code: 47.\nDB::Exception: Cannot parse input',
        ),
    ],
    ids=['sql-tail', 'parameters-tail', 'detail-block', 'before-then-sql'],
)
def test_a_str_shaped_clickhouse_message_is_cut_at_the_earlier_of_the_backstop_and_clickhouses_markers(
    base, text, expected
):
    """Constructed: ClickHouse's markers are added to the backstop's on such a message, never put in its place.

    A message that opens as ``str()`` of ClickHouse's exception does, and then carries a SQLAlchemy or
    PostgreSQL tail, is cut at the first marker of either kind, so nothing the backstop removed comes back.
    """
    result = base._format_db_error(_driver_error(text))

    assert result == expected
    assert 'QA_CANARY' not in result


# ---------------------------------------------------------------------------
# MySQL's own text that looks like ClickHouse's stays whole
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'key',
    ['signal_db_exception', 'signal_multiline_db', 'signal_class_prefix', 'signal_forged_code_other_errno'],
)
def test_a_mysql_signal_that_imitates_clickhouses_text_stays_whole(base, key):
    """Live (MySQL 8.4.11): a ``SIGNAL`` whose text is written like ClickHouse's but is not ClickHouse's.

    ``DB::Exception: tenant QA_APP_T1 rejected. Upload failed at position 3 of batch`` is review item F; the
    others open on a later line, behind the driver's repeated class name, or behind ``Code: 47.`` while the
    errno is 1644. None carries ``Code: <its own errno>.``, which ClickHouse's MySQL interface always writes.
    """
    errno, text = _LIVE[f'mysql84.{key}']

    assert base._format_db_error(_mysql(errno, text)) == f'Error {errno}: {text}'


def test_a_mysql_signal_that_forges_clickhouses_whole_prefix_is_cut_and_nothing_leaks(base):
    """Live, and an accepted limit: the prefix is spelled out with the errno, so the text is cut at `` before: '``.

    ``SIGNAL ... SET MYSQL_ERRNO = 47, MESSAGE_TEXT = 'Code: 47. DB::Exception: app text before: ''x'' kept'``.
    Such a message cannot be told from ClickHouse's own over the same wire. The application's text is shortened,
    and nothing is returned that the markers cut: the loss is the safe direction.
    """
    errno, text = _LIVE['mysql84.signal_forged_code_same_errno']

    assert base._format_db_error(_mysql(errno, text)) == 'Error 47: DB::Exception: app text'
    assert _LIVE['mysql84.signal_code_prefix'][1].startswith('Code: 1644. DB::Exception:')
    assert base._format_db_error(_mysql(*_LIVE['mysql84.signal_code_prefix'])) == 'Error 1644: DB::Exception: app text'


# ---------------------------------------------------------------------------
# Items A and B of the review: more input echoed back after a ClickHouse parse error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('server', ['ch23', 'ch25'])
def test_clickhouse_cuts_the_rest_of_the_rows_after_a_null_into_a_non_nullable_column(base, server):
    """Item A: code 53 ``... of type 'UInt32' at: NULL, 'QA_CANARY_N3'), (3, 'QA_CANARY_N4')``.

    ``INSERT INTO qa_rel.t (id, s) SETTINGS input_format_null_as_default = 0 VALUES (1, 'a'), (NULL,
    'QA_CANARY_N3'), (3, 'QA_CANARY_N4')``: live on both servers, on every route that carries the text.
    """
    sentence = "Cannot insert NULL value into a column of type 'UInt32'"
    results = [
        base._format_db_error(_clickhouse(53, _LIVE[f'{server}.c53.native'])),
        base._format_db_error(_dbapi(_server(53, _LIVE[f'{server}.c53.native']))),
        base._format_db_error(_mysql(*_LIVE[f'{server}.c53.mysql'])),
        base._format_db_error(_ClickHouseConnectError(_LIVE[f'{server}.c53.connect'], 53)),
    ]

    assert results == [f'Error 53: DB::Exception: {sentence}'] * 3 + [
        f'Received ClickHouse exception, code: 53, server response: Code: 53. DB::Exception: {sentence}'
    ]
    assert all('QA_CANARY_N3' not in result and 'QA_CANARY_N4' not in result for result in results)


@pytest.mark.parametrize('server', ['ch23', 'ch25'])
def test_clickhouse_cuts_the_expression_it_could_not_deduce_a_template_for(base, server):
    """Item A: code 62 ``Cannot deduce template of expression: <expr>``.

    Live on both servers with ``SETTINGS input_format_values_interpret_expressions = 0``, which makes
    ClickHouse report an expression it cannot template instead of evaluating it: ``VALUES (1, lower('A')),
    (2, lower((('QA_CANARY_D3')))), ...``. The sentence stays; the expression, bound value included, goes.
    """
    expected = 'Error 62: DB::Exception: Cannot deduce template of expression'
    results = [
        base._format_db_error(_clickhouse(62, _LIVE[f'{server}.deduce.native'])),
        base._format_db_error(_mysql(*_LIVE[f'{server}.deduce.mysql'])),
        # ``(1 + 1)`` in a column whose first row used a template: no bound value, but the same cut.
        base._format_db_error(_clickhouse(62, _LIVE[f'{server}.deduce_paren.native'])),
    ]

    assert results == [expected] * 3
    assert 'QA_CANARY_D3' not in results[0]


@pytest.mark.parametrize('server', ['ch23', 'ch25'])
def test_clickhouse_cuts_the_expression_it_calls_not_constant(base, server):
    """Code 36 ``... is not a constant expression (result column not found): <expr>``.

    ``INSERT ... VALUES (1, 'a'), (2, arrayJoin(['QA_CANARY_D7'])), ...``: live on both servers. Found while
    probing item A; the expression is the caller's, with the bound value in it.
    """
    sentence = (
        'Element of set in IN, VALUES, or LIMIT, or aggregate function parameter, '
        'or a table function argument is not a constant expression (result column not found)'
    )
    results = [
        base._format_db_error(_clickhouse(36, _LIVE[f'{server}.notconst.native'])),
        base._format_db_error(_ClickHouseConnectError(_LIVE[f'{server}.notconst.connect'], 36)),
    ]

    assert results == [
        f'Error 36: DB::Exception: {sentence}',
        f'Received ClickHouse exception, code: 36, server response: Code: 36. DB::Exception: {sentence}',
    ]
    assert all('QA_CANARY_D7' not in result for result in results)


def test_clickhouse_cuts_a_not_constant_expression_whose_text_holds_a_bound_value_on_23_8(base):
    """Live (23.8): ``toString('QA_CANARY_SB' IN (nope))`` is printed after ``(result column not found):``.

    The shape a reviewer's probe found; on 25.8 the same statement fails earlier with code 47 and an ``in
    scope`` echo, covered below.
    """
    result = base._format_db_error(_clickhouse(36, _LIVE['ch23.scope_in_fn.native']))

    assert result.endswith('is not a constant expression (result column not found)')
    assert 'QA_CANARY_SB' not in result


@pytest.mark.parametrize(
    ('server', 'key', 'canaries', 'expected'),
    [
        # 23.8: ``INSERT INTO qa_rel.t (id, s) VALUES (1, 'a'), (2, 'a'), (3, 'QA_CANARY_C3')`` ... CSV with a bad row.
        (
            'ch23',
            'csv',
            ['QA_CANARY_C1', 'QA_CANARY_C2', 'QA_CANARY_C3'],
            "Error 27: DB::ParsingException: Cannot parse input: expected ','",
        ),
        (
            'ch25',
            'csv',
            ['QA_CANARY_C1', 'QA_CANARY_C2', 'QA_CANARY_C3'],
            "Error 27: DB::Exception: Cannot parse input: expected ','",
        ),
        (
            'ch23',
            'tsv',
            ['QA_CANARY_T1', 'QA_CANARY_T2', 'QA_CANARY_T3'],
            "Error 27: DB::ParsingException: Cannot parse input: expected '\\t'",
        ),
        (
            'ch25',
            'tsv',
            ['QA_CANARY_T1', 'QA_CANARY_T2', 'QA_CANARY_T3'],
            "Error 27: DB::Exception: Cannot parse input: expected '\\t'",
        ),
        # A row with an extra column: no ``before: '`` at all, so only the row diagnostic names the other rows.
        (
            'ch23',
            'row117',
            ['QA_CANARY_C1', 'QA_CANARY_C2'],
            'Error 117: DB::Exception: Expected end of line: (at row 2)',
        ),
        (
            'ch25',
            'row117',
            ['QA_CANARY_C1', 'QA_CANARY_C2'],
            'Error 117: DB::Exception: Expected end of line: (at row 2)',
        ),
        # A negative number for a UInt32: 23.8 prints the diagnostic right after the colon, 25.8 after ``(at row 2)``.
        (
            'ch23',
            'row72',
            ['QA_CANARY_C1', 'QA_CANARY_C2'],
            "Error 72: DB::ParsingException: Unsigned type must not contain '-' symbol",
        ),
        (
            'ch25',
            'row72',
            ['QA_CANARY_C1', 'QA_CANARY_C2'],
            "Error 72: DB::Exception: Unsigned type must not contain '-' symbol: (at row 2)",
        ),
    ],
    ids=['csv-23', 'csv-25', 'tsv-23', 'tsv-25', 'extra-column-23', 'extra-column-25', 'negative-23', 'negative-25'],
)
def test_clickhouse_cuts_the_row_diagnostic_of_a_text_input_format(base, server, key, canaries, expected):
    """Item B: ``Row N: ... parsed text: "<value>"`` restates the values of the rows around the failure.

    Live on both servers: ``INSERT INTO qa_rel.t FORMAT CSV`` / ``TSV`` with a row that does not parse. The
    primary sentence stays, and the row number where the server gives it after the sentence.
    """
    code = int(expected.split(':')[0].split()[1])

    result = base._format_db_error(_clickhouse(code, _LIVE[f'{server}.{key}.native']))

    assert result == expected
    for canary in canaries:
        assert canary not in result


@pytest.mark.parametrize(
    ('key', 'canaries'),
    [
        ('scope_literal', ['QA_CANARY_S3', 'QA_CANARY_S4']),
        ('scope_tuple', ['QA_CANARY_S9', 'QA_CANARY_SA']),
        ('scope_array', ['QA_CANARY_A1', 'QA_CANARY_A2']),
    ],
)
def test_clickhouse_cuts_an_in_scope_echo_of_any_expression_shape(base, key, canaries):
    """Live (25.8): ``in scope <expr>`` where the expression starts with a literal, a tuple or an array.

    ``(2, 'QA_CANARY_S3' = nope)``, ``(2, ('QA_CANARY_S9', nope).1)``, ``(2, ['QA_CANARY_A1', nope][1])``. The
    markers named the shapes of an echo (a statement, ``x AS (``, a lambda, a call); an expression can take
    any other, so ``in scope`` in ClickHouse's own text is cut wherever it stands.
    """
    result = base._format_db_error(_clickhouse(47, _LIVE[f'ch25.{key}.native']))

    assert result == 'Error 47: DB::Exception: Unknown expression or function identifier `nope`'
    for canary in canaries:
        assert canary not in result


def test_clickhouse_text_is_cut_at_in_scope_even_before_a_word(base):
    """Constructed: the price of cutting ``in scope`` unconditionally, stated so it is a choice and not an accident.

    ClickHouse writes the phrase only to introduce the scope it prints, so in a message of its own the words
    after it are an echo. Text that merely reads like prose there loses its tail; nothing leaks. A
    ``throwIf`` message is the caller's own and is protected by its error code instead (see below).
    """
    exc = _clickhouse(47, 'DB::Exception: Identifier is not in scope for this rule')

    assert base._format_db_error(exc) == 'Error 47: DB::Exception: Identifier is not'


def test_clickhouse_keeps_a_throwif_context_that_says_in_scope_in_the_callers_words(base):
    """Constructed, and the same input as ``test_clickhouse_still_passes_a_throwif_runtime_context_through``.

    The runtime context repeats the caller's literal, here ``not in scope for this trigger``. Looking for an
    echo inside it still uses the narrow shapes of an echo, so that sentence does not drop the context although
    ``in scope`` is cut everywhere else.
    """
    exc = _clickhouse(
        395,
        "DB::Exception: not in scope for this trigger: while executing 'FUNCTION throwIf(1_UInt8 :: 1, "
        "'not in scope for this trigger'_String :: 2) -> throwIf(1_UInt8, 'not in scope for this trigger'_String) "
        "UInt8 : 3'",
    )

    result = base._format_db_error(exc)

    assert result.startswith('Error 395: DB::Exception: not in scope for this trigger: while executing')
    assert result.endswith("UInt8 : 3'.")


# ---------------------------------------------------------------------------
# Item E: a ClickHouse sentence that is only the echo
# ---------------------------------------------------------------------------

_ECHO_ONLY = (
    "(the server's message only repeated the statement, so it is not shown here; the full text is in the engine log)"
)


@pytest.mark.parametrize(
    ('make_exc', 'header'),
    [
        (lambda text: _clickhouse(47, text), 'Error 47: '),
        (lambda text: _dbapi(_server(47, text)), 'Error 47: '),
        (lambda text: _mysql(47, f'Code: 47. {text}'), 'Error 47: '),
        (lambda text: _driver_error(_with_trace(f'Code: 47.\n{text}')), 'Code: 47.\n'),
        (
            lambda text: _ClickHouseConnectError(
                f'Received ClickHouse exception, code: 47, server response: Code: 47. {text}', 47
            ),
            'Received ClickHouse exception, code: 47, server response: Code: 47. ',
        ),
    ],
    ids=['sqla-native', 'driver-dbapi', 'mysql-wire', 'str-of-server-exception', 'clickhouse-connect'],
)
def test_clickhouse_message_that_is_only_an_echo_says_so_instead_of_returning_a_bare_header(base, make_exc, header):
    """Constructed: no live statement produced one (47 statements on 23.8 and 25.8, 88 errors, none bare).

    ``DB::Exception: In scope SELECT 'QA_CANARY_E1'`` is the shape: the sentence is the scope and nothing else.
    The caller gets the header and a fixed explanation, never text derived from the cut part.
    """
    result = base._format_db_error(make_exc("DB::Exception: In scope SELECT 'QA_CANARY_E1'"))

    assert result == f'{header}DB::Exception: {_ECHO_ONLY}'


@pytest.mark.parametrize('server', ['ch23', 'ch25'])
def test_clickhouse_syntax_error_keeps_its_sentence_and_gets_no_explanation(base, server):
    """Live: ``Syntax error: failed at position 1 ...`` is cut to ``Syntax error:``, which is not a bare header."""
    assert (
        base._format_db_error(_clickhouse(62, _LIVE[f'{server}.syntax.native']))
        == 'Error 62: DB::Exception: Syntax error:'
    )


@pytest.mark.parametrize('server', ['ch23', 'ch25'])
def test_clickhouse_throwif_with_an_empty_message_gets_no_explanation(base, server):
    """Live: ``SELECT throwIf(1, '')`` has no sentence of its own, but nothing was cut from it.

    The explanation is for a sentence that was cut away, so this keeps its runtime context as before.
    """
    result = base._format_db_error(_clickhouse(395, _LIVE[f'{server}.throwif_empty.native']))

    assert result.startswith('Error 395: DB::Exception: while executing')
    assert _ECHO_ONLY not in result


# ---------------------------------------------------------------------------
# What the change must not touch
# ---------------------------------------------------------------------------


def test_the_backstop_marker_set_is_the_one_develop_has():
    """The shared backstop stays what ``_DB_ERROR_DETAIL`` was before ClickHouse-only markers were added.

    Review thread r4319010485: the old ClickHouse markers (and only those) live in the backstop, so nothing
    ClickHouse-only reaches an unknown driver's prose. Compared with whitespace (insignificant in the verbose
    pattern) removed, as a literal.
    """
    from ai.common.database import db_global_base

    pattern = re.sub(r'(?<!\\)\s+', '', db_global_base._DB_ERROR_DETAIL.pattern)

    assert pattern == (
        r'\s*(?:\[SQL:|\[parameters:|\[cached\ since|\[generated\ in|\(Background\ on\ this\ error|LINE\ \d+:'
        r'|Stack\ trace:|failed\ at\ position|while\ processing\ query:|,\ required\ columns:'
        r'|[Ii]n\ scope\ (?=\(?(?:SELECT|INSERT|WITH|CREATE|ALTER|DROP|DELETE|UPDATE|EXPLAIN)\b))'
        r'|\n[\t]*(?:DETAIL:|HINT:|CONTEXT:|QUERY:|STATEMENT:)'
    )


def test_the_dbapi_layer_classifies_clickhouse_text_once(base, monkeypatch):
    """The text of ``clickhouse_driver.dbapi``'s error is classified once, not once to unwrap it and once to cut it."""
    from ai.common.database import db_global_base

    calls = []

    class _Counting:
        def __init__(self, pattern):
            self._pattern = pattern

        def match(self, string, *args):
            calls.append(string)
            return self._pattern.match(string, *args)

    monkeypatch.setattr(db_global_base, '_CLICKHOUSE_TEXT', _Counting(db_global_base._CLICKHOUSE_TEXT))

    base._format_db_error(_dbapi(_server(27, _LIVE['ch25.c27.native'])))

    assert len(calls) == 1
