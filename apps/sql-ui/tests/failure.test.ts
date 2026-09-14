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
// SQL FAILURE — unit tests for what the app says when a statement fails
// =============================================================================
//
// Each expectation is tied to a literal the backend actually produces; the
// line references are in the module's header.
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { describeFailure, maxRowsText } from '../src/sql/failure';
import { applyRowLimit } from '../src/sql/batch';

describe('describeFailure', () => {
	it('puts the first line of the driver text in the headline', () => {
		const notice = describeFailure("Table 'sample_shop.custmers' doesn't exist\n(1146)");
		assert.equal(notice.headline, "Database reported: Table 'sample_shop.custmers' doesn't exist");
	});

	it('keeps the whole message verbatim', () => {
		const notice = describeFailure('line one\nline two');
		assert.equal(notice.verbatim, 'line one\nline two');
	});

	it('recognises the node generic placeholder', () => {
		const notice = describeFailure('SQL execution failed (check server logs for details)');
		assert.equal(notice.generic, true);
	});

	it('does not call real driver text generic', () => {
		assert.equal(describeFailure('syntax error at or near "slect"').generic, false);
	});

	it('recognises the allow_execute refusal', () => {
		const notice = describeFailure('execute tool is disabled for this node (set allow_execute=true)');
		assert.equal(notice.allowExecuteOff, true);
	});

	it('does not claim allow_execute for an ordinary failure', () => {
		assert.equal(describeFailure('deadlock found when trying to get lock').allowExecuteOff, false);
	});

	it('reads the node row cap out of an overflow', () => {
		assert.equal(describeFailure('EXECUTE query exceeded max_execute_rows=1000').maxExecuteRows, 1000);
	});

	it('reports no cap when the failure is unrelated', () => {
		assert.equal(describeFailure('connection reset').maxExecuteRows, null);
	});

	it('survives an empty message', () => {
		const notice = describeFailure('');
		assert.equal(notice.headline, 'Database reported: ');
		assert.equal(notice.generic, false);
	});
});

describe('maxRowsText', () => {
	it('names the cap', () => {
		assert.equal(maxRowsText(1000), 'The node caps results at 1,000 rows; choose a lower limit or add LIMIT.');
	});
});

describe('applyRowLimit', () => {
	it('appends a limit to a SELECT', () => {
		assert.deepEqual(applyRowLimit('SELECT * FROM orders', '200'), { sql: 'SELECT * FROM orders LIMIT 200', limit: 200 });
	});

	it('drops a trailing semicolon before appending', () => {
		assert.equal(applyRowLimit('SELECT 1;', '200').sql, 'SELECT 1 LIMIT 200');
	});

	it('applies no limit for All', () => {
		assert.deepEqual(applyRowLimit('SELECT * FROM orders', 'All'), { sql: 'SELECT * FROM orders', limit: null });
	});

	it('leaves a statement that already limits itself alone', () => {
		assert.deepEqual(applyRowLimit('SELECT * FROM orders LIMIT 5', '200'), { sql: 'SELECT * FROM orders LIMIT 5', limit: null });
	});

	it('leaves an UPDATE alone', () => {
		assert.deepEqual(applyRowLimit('UPDATE orders SET a = 1', '200'), { sql: 'UPDATE orders SET a = 1', limit: null });
	});

	it('leaves DDL alone', () => {
		assert.equal(applyRowLimit('CREATE TABLE t (id INT)', '200').limit, null);
	});

	it('leaves SHOW and EXPLAIN alone', () => {
		assert.equal(applyRowLimit('SHOW TABLES', '200').limit, null);
		assert.equal(applyRowLimit('EXPLAIN SELECT 1', '200').limit, null);
	});

	it('limits a read-only WITH chain', () => {
		assert.equal(applyRowLimit('WITH r AS (SELECT 1) SELECT * FROM r', '200').limit, 200);
	});

	it('leaves a data-modifying WITH chain alone', () => {
		assert.equal(applyRowLimit('WITH gone AS (DELETE FROM t RETURNING *) SELECT * FROM gone', '200').limit, null);
	});

	it('limits a parenthesised set expression', () => {
		assert.equal(applyRowLimit('(SELECT 1) UNION (SELECT 2)', '200').limit, 200);
	});

	it('sees through a leading comment', () => {
		assert.equal(applyRowLimit('-- daily\nSELECT * FROM orders', '200').limit, 200);
	});

	it('does not see a LIMIT that only exists in a comment', () => {
		assert.equal(applyRowLimit('SELECT * FROM orders -- no LIMIT here', '200').limit, 200);
	});
});
