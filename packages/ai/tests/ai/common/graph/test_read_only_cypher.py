# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Token-level read-path check used by Neo4j's read_query (defence in depth)."""

from __future__ import annotations

import pytest

from ai.common.graph.cypher_safety import CypherRefused, check_read_only_cypher
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
