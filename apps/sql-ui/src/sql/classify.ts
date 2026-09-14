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
// SQL — STATEMENT CLASSIFICATION AND PATTERN CHECK
// =============================================================================
//
// Two lexical judgements, both made on comment-stripped text and both honest
// about being guesses:
//
//   `classifyStatement` — what kind of statement this is. The runner uses it
//   to decide whether a failed call may be retried with a fresh token
//   (`idempotent`), so the rule is conservative: anything that is not clearly
//   read-only is not a read. `EXPLAIN ANALYZE` really executes its inner
//   statement, so it is classified by that statement, not as a read.
//
//   `patternCheck` — whether the statement matches one of the four shapes the
//   confirmation dialog asks about. This is a TEXT CHECK, not a database
//   safeguard, and the UI says exactly that. It reads the leading keyword and,
//   for UPDATE/DELETE, looks for a WHERE in code at parenthesis depth 0. It
//   therefore flags a DELETE whose only WHERE sits inside a subquery (a false
//   positive that costs one extra confirmation) and cannot see anything the
//   database would do with triggers, rules, or cascading constraints.
// =============================================================================

import type { SqlDialect } from '../connect';
import { hasTopLevelKeyword, stripSqlComments } from './split';

// =============================================================================
// TYPES
// =============================================================================

/**
 * What a statement does, by text pattern.
 *
 * - `read` — returns rows and changes nothing (SELECT, SHOW, EXPLAIN, DESCRIBE).
 * - `write` — changes rows (INSERT, UPDATE, DELETE, REPLACE, MERGE, TRUNCATE).
 * - `ddl` — changes the schema (CREATE, ALTER, DROP, RENAME).
 * - `tx` — transaction control, which has no effect through this app's
 *   per-call autocommit execution path.
 * - `other` — anything else (SET, USE, CALL, GRANT, an empty buffer).
 */
export type StatementKind = 'read' | 'write' | 'ddl' | 'tx' | 'other';

/** What the pattern check saw. */
export interface IPatternFinding {
	/**
	 * The shape detected, phrased for the confirmation dialog's sentence
	 * `Pattern check: <kind> detected.` — e.g. `DELETE without WHERE`.
	 */
	kind: string;
}

// =============================================================================
// KEYWORD TABLES
// =============================================================================

/** Leading keywords that return rows and change nothing. */
const READ_LEADERS = /^(select|show|describe|desc)\b/i;

/** Leading keywords that change rows. */
const WRITE_LEADERS = /^(insert|update|delete|replace|merge|truncate)\b/i;

/** Leading keywords that change the schema. */
const DDL_LEADERS = /^(create|alter|drop|rename)\b/i;

/** Transaction-control statements (no effect on this app's execution path). */
const TX_LEADERS = /^(begin|start\s+transaction|commit|rollback|savepoint|release\b)/i;

/** `SET` forms that are transaction control rather than a session variable. */
const TX_SET = /^set\s+(?:session\s+|global\s+|local\s+)?(?:autocommit|transaction)\b/i;

/**
 * The `EXPLAIN` prefix: the keyword, an optional parenthesised option list, and
 * any bare option words before the statement being explained.
 */
const EXPLAIN_PREFIX = /^explain\s*(?:\([^)]*\)\s*)?(?:(?:analyz[se]|verbose|extended|partitions|costs|buffers|settings|summary|timing|wal|format\s*=?\s*\w+)\s+)*/i;

/** Data-modifying keywords that can appear inside a CTE chain. */
const CTE_WRITE = /\b(insert|update|delete|merge|replace)\b/i;

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Normalise a statement for leading-keyword matching: comments removed,
 * whitespace collapsed, leading `(` of a parenthesised set expression dropped.
 *
 * @param sql - The statement text.
 * @param dialect - The engine dialect.
 * @returns The comment-free text, trimmed.
 */
function normalize(sql: string, dialect: SqlDialect): string {
	return stripSqlComments(sql, dialect).replace(/^[\s(]+/, '').trim();
}

// =============================================================================
// CLASSIFICATION
// =============================================================================

/**
 * Classify a single statement by its leading keyword.
 *
 * A `WITH` chain is a read only when no data-modifying keyword appears
 * anywhere in it — a deliberately blunt rule, since `WITH gone AS (DELETE ...)`
 * must never be treated as read-only. The cost is that a CTE containing the
 * bare word `delete` in code (not in a literal, which is not visible here
 * either way) is over-classified as a write, which is the safe direction.
 *
 * @param sql - One statement (no terminator needed).
 * @param dialect - The engine dialect; decides comment syntax.
 * @returns The statement kind.
 */
export function classifyStatement(sql: string, dialect: SqlDialect = 'unknown'): StatementKind {
	const head = normalize(sql, dialect);
	if (!head) return 'other';

	// EXPLAIN: read, UNLESS it is an ANALYZE form, which runs the statement.
	if (/^explain\b/i.test(head)) {
		const prefix = EXPLAIN_PREFIX.exec(head)?.[0] ?? 'explain';
		const inner = head.slice(prefix.length).trim();
		if (!/\banaly[sz]e\b/i.test(prefix)) return 'read';
		if (!inner || /^explain\b/i.test(inner)) return 'read';
		return classifyStatement(inner, dialect);
	}

	if (TX_SET.test(head)) return 'tx';
	if (TX_LEADERS.test(head)) return 'tx';
	if (READ_LEADERS.test(head)) return 'read';
	if (WRITE_LEADERS.test(head)) return 'write';
	if (DDL_LEADERS.test(head)) return 'ddl';
	if (/^with\b/i.test(head)) return CTE_WRITE.test(head) ? 'write' : 'read';
	return 'other';
}

// =============================================================================
// PATTERN CHECK
// =============================================================================

/**
 * Look for the four statement shapes the confirmation dialog asks about:
 * UPDATE or DELETE with no top-level WHERE, TRUNCATE, DROP, ALTER.
 *
 * LIMITS, stated plainly because the dialog does too:
 * - A WHERE inside a string literal or a comment does not count (correct).
 * - A WHERE that exists only inside a subquery or a `USING (...)` clause does
 *   not count either, so such a statement is flagged (extra confirmation).
 * - A WHERE clause that matches every row (`WHERE 1=1`) passes the check.
 * - Nothing here knows what the database will do with triggers or cascades.
 *
 * @param sql - One statement.
 * @param dialect - The engine dialect.
 * @returns The finding, or null when nothing matched.
 */
export function patternCheck(sql: string, dialect: SqlDialect = 'unknown'): IPatternFinding | null {
	const head = normalize(sql, dialect);
	if (!head) return null;

	if (/^truncate\b/i.test(head)) return { kind: 'TRUNCATE' };
	if (/^drop\b/i.test(head)) return { kind: 'DROP' };
	if (/^alter\b/i.test(head)) return { kind: 'ALTER' };

	const verb = /^update\b/i.test(head) ? 'UPDATE' : /^delete\b/i.test(head) ? 'DELETE' : null;
	if (!verb) return null;
	if (hasTopLevelKeyword(head, 'where', dialect)) return null;
	return { kind: `${verb} without WHERE` };
}
