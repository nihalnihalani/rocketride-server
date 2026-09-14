// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// =============================================================================
// SQL CLASSIFY — unit tests for statement kinds and the pattern check
// =============================================================================
//
// Two contracts, both safety-relevant:
//   1. `classifyStatement` decides whether the runner may pass
//      `idempotent: true` (which permits ONE silent retry with a fresh token).
//      A statement that changes data must never be classified 'read'.
//   2. `patternCheck` is a TEXT heuristic. Its job is to be honest about what
//      it can and cannot see; the false positives it is allowed to have are
//      pinned here so nobody "fixes" them into false negatives.
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { StatementKind } from '../src/sql/classify';
import { classifyStatement, patternCheck } from '../src/sql/classify';

// =============================================================================
// CLASSIFICATION
// =============================================================================

/** One classification case. */
interface IKindCase {
	/** The statement text. */
	sql: string;
	/** The kind it must be reported as. */
	kind: StatementKind;
}

const KIND_CASES: IKindCase[] = [
	// Reads.
	{ sql: 'SELECT 1', kind: 'read' },
	{ sql: '  select * from orders  ', kind: 'read' },
	{ sql: '(SELECT 1) UNION (SELECT 2)', kind: 'read' },
	{ sql: '-- a note\nSELECT 1', kind: 'read' },
	{ sql: '/* lead */ SELECT 1', kind: 'read' },
	{ sql: 'WITH recent AS (SELECT * FROM orders) SELECT * FROM recent', kind: 'read' },
	{ sql: 'SHOW TABLES', kind: 'read' },
	{ sql: 'SHOW CREATE TABLE orders', kind: 'read' },
	{ sql: 'EXPLAIN SELECT * FROM orders', kind: 'read' },
	{ sql: 'EXPLAIN FORMAT=JSON SELECT * FROM orders', kind: 'read' },
	{ sql: 'EXPLAIN (FORMAT JSON) SELECT * FROM orders', kind: 'read' },
	{ sql: 'DESCRIBE orders', kind: 'read' },
	{ sql: 'DESC orders', kind: 'read' },
	{ sql: 'VALUES (1)', kind: 'other' },

	// EXPLAIN ANALYZE really runs the statement — never 'read'.
	{ sql: 'EXPLAIN ANALYZE DELETE FROM orders', kind: 'write' },
	{ sql: 'EXPLAIN (ANALYZE, BUFFERS) UPDATE orders SET a = 1', kind: 'write' },
	{ sql: 'EXPLAIN ANALYZE SELECT * FROM orders', kind: 'read' },

	// Writes.
	{ sql: 'INSERT INTO orders (id) VALUES (1)', kind: 'write' },
	{ sql: 'UPDATE orders SET total = 1', kind: 'write' },
	{ sql: 'DELETE FROM orders', kind: 'write' },
	{ sql: 'REPLACE INTO orders (id) VALUES (1)', kind: 'write' },
	{ sql: 'MERGE INTO orders USING staging ON (1=1)', kind: 'write' },
	{ sql: 'TRUNCATE TABLE orders', kind: 'write' },
	{ sql: 'WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone', kind: 'write' },

	// DDL.
	{ sql: 'CREATE TABLE t (id INT)', kind: 'ddl' },
	{ sql: 'ALTER TABLE t ADD COLUMN c INT', kind: 'ddl' },
	{ sql: 'DROP TABLE t', kind: 'ddl' },
	{ sql: 'RENAME TABLE a TO b', kind: 'ddl' },
	{ sql: 'CREATE INDEX ix ON t (id)', kind: 'ddl' },

	// Transaction control.
	{ sql: 'BEGIN', kind: 'tx' },
	{ sql: 'START TRANSACTION', kind: 'tx' },
	{ sql: 'COMMIT', kind: 'tx' },
	{ sql: 'ROLLBACK', kind: 'tx' },
	{ sql: 'ROLLBACK TO SAVEPOINT s1', kind: 'tx' },
	{ sql: 'SAVEPOINT s1', kind: 'tx' },
	{ sql: 'RELEASE SAVEPOINT s1', kind: 'tx' },
	{ sql: 'SET autocommit = 0', kind: 'tx' },
	{ sql: 'SET GLOBAL autocommit = 0', kind: 'tx' },
	{ sql: 'SET TRANSACTION ISOLATION LEVEL SERIALIZABLE', kind: 'tx' },
	{ sql: 'SET SESSION TRANSACTION READ ONLY', kind: 'tx' },

	// Everything else.
	{ sql: 'SET @x = 1', kind: 'other' },
	{ sql: 'USE sample_shop', kind: 'other' },
	{ sql: 'CALL do_thing()', kind: 'other' },
	{ sql: 'GRANT SELECT ON t TO u', kind: 'other' },
	{ sql: '', kind: 'other' },
	{ sql: '-- only a comment', kind: 'other' },
];

describe('classifyStatement', () => {
	for (const testCase of KIND_CASES) {
		it(`${JSON.stringify(testCase.sql)} -> ${testCase.kind}`, () => {
			assert.equal(classifyStatement(testCase.sql), testCase.kind);
		});
	}

	it('ignores a keyword that only appears inside a literal', () => {
		assert.equal(classifyStatement("SELECT 'DELETE FROM orders' AS t"), 'read');
	});

	it('does not match a keyword inside a longer word', () => {
		assert.equal(classifyStatement('SELECT deleted_at FROM orders'), 'read');
	});
});

// =============================================================================
// PATTERN CHECK
// =============================================================================

describe('patternCheck', () => {
	it('flags DELETE with no WHERE', () => {
		assert.deepEqual(patternCheck('DELETE FROM orders'), { kind: 'DELETE without WHERE' });
	});

	it('passes DELETE with a top-level WHERE', () => {
		assert.equal(patternCheck('DELETE FROM orders WHERE id = 5'), null);
	});

	it('passes DELETE whose WHERE holds a subquery', () => {
		assert.equal(patternCheck('DELETE FROM orders WHERE id IN (SELECT id FROM stale)'), null);
	});

	it('flags UPDATE with no WHERE', () => {
		assert.deepEqual(patternCheck('UPDATE orders SET total = 0'), { kind: 'UPDATE without WHERE' });
	});

	it('passes UPDATE with a top-level WHERE', () => {
		assert.equal(patternCheck('UPDATE orders SET total = 0 WHERE id = 5'), null);
	});

	it('does NOT count a WHERE that only exists inside a string literal', () => {
		assert.deepEqual(patternCheck("UPDATE orders SET note = 'where it went'"), { kind: 'UPDATE without WHERE' });
	});

	it('does NOT count a WHERE that only exists inside a comment', () => {
		assert.deepEqual(patternCheck('DELETE FROM orders -- WHERE id = 5'), { kind: 'DELETE without WHERE' });
	});

	it('flags a WHERE that only exists inside a subquery (documented false positive)', () => {
		assert.deepEqual(
			patternCheck('DELETE FROM orders USING (SELECT id FROM stale WHERE x) s'),
			{ kind: 'DELETE without WHERE' },
		);
	});

	it('flags TRUNCATE', () => {
		assert.deepEqual(patternCheck('TRUNCATE TABLE orders'), { kind: 'TRUNCATE' });
	});

	it('flags DROP', () => {
		assert.deepEqual(patternCheck('DROP TABLE orders'), { kind: 'DROP' });
	});

	it('flags ALTER', () => {
		assert.deepEqual(patternCheck('ALTER TABLE orders ADD COLUMN c INT'), { kind: 'ALTER' });
	});

	it('passes a plain SELECT', () => {
		assert.equal(patternCheck('SELECT * FROM orders'), null);
	});

	it('passes an INSERT', () => {
		assert.equal(patternCheck('INSERT INTO orders (id) VALUES (1)'), null);
	});

	it('passes a commented-out DELETE', () => {
		assert.equal(patternCheck('-- DELETE FROM orders\nSELECT 1'), null);
	});

	it('flags a mysql multi-table DELETE with no WHERE', () => {
		assert.deepEqual(patternCheck('DELETE a FROM orders a'), { kind: 'DELETE without WHERE' });
	});

	it('flags a clickhouse ALTER ... DELETE as ALTER', () => {
		assert.deepEqual(patternCheck('ALTER TABLE orders DELETE WHERE id = 5'), { kind: 'ALTER' });
	});
});
