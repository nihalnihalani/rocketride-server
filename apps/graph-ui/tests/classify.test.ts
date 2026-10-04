// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CYPHER CLASSIFIER (text check) AND PROCEDURE NORMALISATION
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyStatement, leadingVerb, patternCheck, statementKind } from '../src/cypher/classify';
import { codeTokens, tokenize } from '../src/cypher/lexer';
import { VETTED_PROCEDURES, isVettedProcedure, normalizeProcedure } from '../src/cypher/procedures';

const READS = [
	'MATCH (n) RETURN n LIMIT 25',
	'match (n) return n',
	'MATCH (a)--(b) RETURN a, b',
	'MATCH (a)-[r:KNOWS*1..3]->(b) RETURN a, r, b',
	'OPTIONAL MATCH (n)-[r]-(m) RETURN n, r, m',
	'optional   match (n) return n',
	'WITH 1 AS x RETURN x',
	'UNWIND [1, 2, 3] AS i RETURN i',
	'RETURN 1',
	'MATCH (n) WHERE n.id = $id RETURN n',
	// Words that spell a write clause but are not one.
	'MATCH (n) RETURN n.delete, n.set, n.create, n.merge, n.remove',
	'MATCH (n:Delete)-[:SET]->(m:Create) RETURN n, m',
	'MATCH (n:`CREATE`) RETURN n',
	"RETURN 'DELETE everything; CREATE (n) SET n.x = 1'",
	'// DELETE all\nMATCH (n) RETURN n',
	'MATCH (n) /* SET n.x = 1 */ RETURN n',
	'RETURN {create: 1, set: 2, delete: 3}',
	'MATCH (n) RETURN {a: 1, merge: n.x}',
	'MATCH (start)-[:NEXT]->(end) RETURN start, end',
	'MATCH (n) WITH n AS stop RETURN stop',
	'MATCH (ñ:Café) RETURN ñ',
	'WITH 1 AS deleteé RETURN deleteé',
	'MATCH (n) RETURN n.deleted, n.created',
	// Vetted procedures, in every spelling.
	'CALL db.labels()',
	'call DB.Labels() YIELD label RETURN label',
	'CALL `db`.`labels`()',
	'CALL db . relationshipTypes ( )',
	'CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey',
	'CALL db.schema.visualization()',
	'CALL db.schema.nodeTypeProperties()',
	'CALL db.schema.relTypeProperties() YIELD relType RETURN relType',
	'CALL db.labels',
	// Subqueries are scanned, not refused.
	'MATCH (n) CALL { WITH n MATCH (n)--(m) RETURN count(m) AS c } RETURN n, c',
	'MATCH (n) CALL (n) { MATCH (n)--(m) RETURN count(m) AS c } RETURN n, c',
	'MATCH (n) WHERE EXISTS { MATCH (n)--(:X) } RETURN n',
	// Read-only SHOW.
	'SHOW INDEXES',
	'SHOW ALL CONSTRAINTS',
	'show unique constraints',
	'SHOW PROCEDURES',
	'SHOW FUNCTIONS',
	'SHOW TRANSACTIONS',
	'SHOW DATABASES',
	'SHOW SETTINGS',
];

const WRITES: Array<[string, string]> = [
	['CREATE (n:Person {name: $n})', 'CREATE'],
	['MERGE (n:Person {id: $id})', 'MERGE'],
	['MATCH (n) SET n.x = 1', 'SET'],
	['MATCH (n) SET n:Extra', 'SET'],
	['MATCH (n) REMOVE n.x', 'REMOVE'],
	['MATCH (n) DELETE n', 'DELETE'],
	['MATCH (n) DETACH DELETE n', 'DETACH DELETE'],
	['MATCH (n) WITH n CREATE (m)', 'CREATE'],
	['UNWIND [1] AS x MERGE (m {id: x}) ON CREATE SET m.a = 1', 'MERGE'],
	['MATCH (n) FOREACH (x IN [1] | SET n.v = x)', 'FOREACH'],
	["LOAD CSV FROM 'file:///x.csv' AS row RETURN row", 'LOAD CSV'],
	['DROP INDEX person_name', 'DROP'],
	['CREATE INDEX FOR (n:Person) ON (n.name)', 'CREATE'],
	['ALTER DATABASE neo4j SET ACCESS READ ONLY', 'ALTER'],
	['GRANT ROLE reader TO bob', 'GRANT'],
	['DENY READ {*} ON GRAPH * TO reader', 'DENY'],
	['REVOKE ROLE reader FROM bob', 'REVOKE'],
	['START DATABASE neo4j', 'START'],
	['STOP DATABASE neo4j', 'STOP'],
	['RENAME ROLE old TO new', 'RENAME'],
	['TERMINATE TRANSACTIONS "t-1"', 'TERMINATE'],
	['SHOW TRANSACTIONS YIELD transactionId TERMINATE TRANSACTIONS transactionId', 'TERMINATE TRANSACTIONS'],
	['DEALLOCATE DATABASES FROM SERVER s1', 'DEALLOCATE'],
	// Procedures outside the reviewed list, in every disguise.
	["CALL apoc.cypher.runWrite('CREATE (n)', {})", 'CALL apoc.cypher.runWrite'],
	['CALL apoc.periodic.iterate("a", "b", {})', 'CALL apoc.periodic.iterate'],
	["CALL db.createLabel('Foo')", 'CALL db.createLabel'],
	['CALL DB.CREATELABEL("x")', 'CALL DB.CREATELABEL'],
	["CALL `apoc`.`cypher`.`runWrite`('x', {})", 'CALL apoc.cypher.runWrite'],
	['CALL `db.labels`()', 'CALL db.labels'],
	['CALL db.schema.somethingNew()', 'CALL db.schema.somethingNew'],
	['CALL db.labels.extra()', 'CALL db.labels.extra'],
	['CALL dbms.components()', 'CALL dbms.components'],
	['CALL ;', 'CALL'],
	// Nested writes and nested procedures.
	['MATCH (n) CALL { WITH n SET n.x = 1 } RETURN n', 'SET'],
	['MATCH (n) CALL { WITH n CALL apoc.cypher.runWrite("x", {}) YIELD value RETURN value } RETURN n', 'CALL apoc.cypher.runWrite'],
	['CALL { CREATE (n) RETURN n } RETURN n', 'CREATE'],
	['MATCH (n) WHERE EXISTS { MATCH (n)--(m) SET m.x = 1 } RETURN n', 'SET'],
	// Not a read start, and not on the list.
	['EXPLAIN MATCH (n) RETURN n', 'unrecognized statement (EXPLAIN)'],
	['PROFILE MATCH (n) RETURN n', 'unrecognized statement (PROFILE)'],
	['USE neo4j MATCH (n) RETURN n', 'unrecognized statement (USE)'],
	['SHOW USERS', 'unrecognized statement (SHOW)'],
	['SHOW ROLES', 'unrecognized statement (SHOW)'],
	['FOO bar', 'unrecognized statement (FOO)'],
	['1 + 1', 'unrecognized statement (1)'],
	['(n)', 'unrecognized statement (()'],
	// Malformed text never counts as a read.
	["MATCH (n) RETURN 'abc", 'unterminated string'],
	['MATCH (n) /* RETURN n', 'unterminated comment'],
	['MATCH (n:`Person) RETURN n', 'unterminated quoted name'],
];

test('reads are classified read, with no findings', () => {
	for (const text of READS) {
		const result = classifyStatement(text);
		assert.equal(result.kind, 'read', `${text} => ${JSON.stringify(result.findings)}`);
		assert.deepEqual(result.findings, [], text);
		assert.equal(patternCheck(text), null, text);
	}
});

test('writes, administration, unvetted calls and malformed text are classified write', () => {
	for (const [text, label] of WRITES) {
		const result = classifyStatement(text);
		assert.equal(result.kind, 'write', text);
		assert.ok(result.findings.length > 0, text);
		const check = patternCheck(text);
		assert.ok(check, text);
		assert.ok(check.kind.includes(label), `${text}: pattern "${check.kind}" should name "${label}"`);
	}
});

test('every finding points at text inside the statement', () => {
	for (const [text] of WRITES) {
		for (const finding of classifyStatement(text).findings) {
			assert.ok(finding.start >= 0 && finding.end <= text.length && finding.end > finding.start, `${text}: ${JSON.stringify(finding)}`);
		}
	}
});

test('an empty statement (whitespace and comments only) is empty, not read', () => {
	for (const text of ['', '   ', '// nothing', '/* nothing */', '\n// a\n/* b */\n']) {
		assert.equal(statementKind(text), 'empty', JSON.stringify(text));
		assert.equal(patternCheck(text), null);
		assert.equal(leadingVerb(text), '');
	}
});

test('inserting comments between tokens never changes the classification', () => {
	for (const text of [...READS, ...WRITES.map(([t]) => t)]) {
		const expected = statementKind(text);
		const all = tokenize(text);
		// A text with an unterminated string, comment or name has no token boundary to put a comment on.
		if (all.some((t) => t.unterminated)) continue;
		const tokens = codeTokens(all);
		const spaced = tokens.map((t) => t.text).join(' /* c */ ');
		const lined = tokens.map((t) => t.text).join(' // c\n');
		// Joining with a separator can glue nothing together: tokens were already separated by a boundary.
		assert.equal(statementKind(spaced), expected, `block comments: ${text}`);
		assert.equal(statementKind(lined), expected, `line comments: ${text}`);
	}
});

test('mixed-case keywords and extra whitespace do not hide a write', () => {
	assert.equal(statementKind('match (n)\n\t\tSeT n.x = 1'), 'write');
	assert.equal(statementKind('MATCH (n) dEtAcH\n  dElEtE n'), 'write');
	assert.equal(statementKind('lOaD   cSv from "x" as r return r'), 'write');
});

test('leading verbs for labels', () => {
	assert.equal(leadingVerb('match (n) return n'), 'MATCH');
	assert.equal(leadingVerb('optional  match (n) return n'), 'OPTIONAL MATCH');
	assert.equal(leadingVerb('CREATE (n)'), 'CREATE');
	assert.equal(leadingVerb('// c\nCALL db.labels()'), 'CALL');
	assert.equal(leadingVerb('(n)'), '(');
});

test('pattern check phrasing joins distinct findings once each', () => {
	assert.equal(patternCheck('CREATE (n) SET n.x = 1 SET n.y = 2')?.kind, 'CREATE, SET');
	assert.equal(patternCheck('MATCH (n) DETACH DELETE n')?.kind, 'DETACH DELETE');
	assert.equal(patternCheck("CALL apoc.cypher.runWrite('x', {})")?.kind, 'CALL apoc.cypher.runWrite');
});

test('the vetted procedure list is exactly the reviewed six, with no wildcard', () => {
	assert.deepEqual(
		VETTED_PROCEDURES.map((entry) => entry.join('.')),
		['db.labels', 'db.relationshiptypes', 'db.propertykeys', 'db.schema.visualization', 'db.schema.nodetypeproperties', 'db.schema.reltypeproperties']
	);
	assert.equal(isVettedProcedure(['db', 'schema', 'brandNewProcedure']), false);
	assert.equal(isVettedProcedure(['db', 'schema']), false);
	assert.equal(isVettedProcedure(['DB', 'Labels']), true);
	// One part that contains a dot is NOT the two-part name it prints like.
	assert.equal(isVettedProcedure(['db.labels']), false);
	assert.deepEqual(normalizeProcedure(['DB', 'Labels']), ['db', 'labels']);
});
