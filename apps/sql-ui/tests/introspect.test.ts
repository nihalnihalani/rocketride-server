// MIT License
//
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
// SQL INTROSPECT — unit tests for the FK-name reader over a fake session
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { ISqlExecuteResult, ISqlSession } from '../src/connect';
import { fetchForeignKeyNames } from '../src/sql/introspect';

// =============================================================================
// FAKE SESSION
// =============================================================================

/** Records the statements a call issued and replays canned rows. */
interface IFakeSession {
	/** The session handed to the module under test. */
	session: ISqlSession;
	/** Every statement the module executed, in order. */
	statements: string[];
}

/**
 * Build a fake ISqlSession that answers every execute with the given rows.
 *
 * @param rows - The rows every execute returns.
 * @returns The fake session and its statement log.
 */
function fakeSession(rows: Record<string, unknown>[] = []): IFakeSession {
	const statements: string[] = [];
	const session = {
		endpoint: { key: 'p:s:n' },
		execute: async (sql: string): Promise<ISqlExecuteResult> => {
			statements.push(sql);
			return { rows, affected_rows: 0 };
		},
		getSchema: async () => ({}),
		refreshSchema: async () => ({}),
		dialect: async () => 'postgres' as const,
	} as unknown as ISqlSession;
	return { session, statements };
}

// =============================================================================
// DIALECT COVERAGE
// =============================================================================

describe('fetchForeignKeyNames dialect coverage', () => {
	it('reads KEY_COLUMN_USAGE scoped to the current database on MySQL', async () => {
		const { session, statements } = fakeSession();
		await fetchForeignKeyNames(session, 'mysql', 'orders');
		assert.equal(statements.length, 1);
		assert.match(statements[0]!, /information_schema\.KEY_COLUMN_USAGE/);
		assert.match(statements[0]!, /TABLE_SCHEMA = DATABASE\(\)/);
		assert.match(statements[0]!, /REFERENCED_TABLE_NAME IS NOT NULL/);
	});

	it('joins through referential_constraints on Postgres and scopes by schema', async () => {
		const { session, statements } = fakeSession();
		await fetchForeignKeyNames(session, 'postgres', 'orders');
		assert.equal(statements.length, 1);
		assert.match(statements[0]!, /information_schema\.referential_constraints/);
		assert.match(statements[0]!, /constraint_type = 'FOREIGN KEY'/);
		assert.match(statements[0]!, /tc\.table_schema = current_schema\(\)/);
	});

	it('returns empty without querying for ClickHouse and unknown engines', async () => {
		for (const dialect of ['clickhouse', 'neo4j', 'unknown'] as const) {
			const { session, statements } = fakeSession([{ name: 'fk', col: 'x', ref: 't' }]);
			assert.deepEqual(await fetchForeignKeyNames(session, dialect, 'orders'), []);
			assert.deepEqual(statements, []);
		}
	});
});

// =============================================================================
// TABLE NAMES ARE ALWAYS QUOTED LITERALS
// =============================================================================

describe('fetchForeignKeyNames literal quoting', () => {
	it('quotes an all-digit table name instead of comparing it as a number', async () => {
		const { session, statements } = fakeSession();
		await fetchForeignKeyNames(session, 'mysql', '2026');
		assert.match(statements[0]!, /TABLE_NAME = '2026'/);
	});

	it('doubles an embedded single quote', async () => {
		const { session, statements } = fakeSession();
		await fetchForeignKeyNames(session, 'postgres', "o'brien");
		assert.match(statements[0]!, /tc\.table_name = 'o''brien'/);
	});
});

// =============================================================================
// ROW MAPPING
// =============================================================================

describe('fetchForeignKeyNames row mapping', () => {
	it('maps name / col / ref onto the constraint shape', async () => {
		const { session } = fakeSession([{ name: 'fk_o_c', col: 'customer_id', ref: 'customers' }]);
		assert.deepEqual(await fetchForeignKeyNames(session, 'mysql', 'orders'), [
			{ name: 'fk_o_c', column: 'customer_id', referredTable: 'customers' },
		]);
	});

	it('coerces missing fields to empty strings and drops nameless rows', async () => {
		const { session } = fakeSession([
			{ col: 'x', ref: 't' },
			{ name: 'fk_ok', col: null, ref: undefined },
		]);
		assert.deepEqual(await fetchForeignKeyNames(session, 'mysql', 'orders'), [
			{ name: 'fk_ok', column: '', referredTable: '' },
		]);
	});

	it('returns an empty list when the catalog query matched nothing', async () => {
		const { session } = fakeSession([]);
		assert.deepEqual(await fetchForeignKeyNames(session, 'postgres', 'orders'), []);
	});
});
