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
//   statement, so it is classified by that statement, not as a read — and
//   `patternCheck` peels the same prefix for the same reason.
//
//   `patternCheck` — whether the statement matches one of the shapes the
//   confirmation dialog asks about. This is a TEXT CHECK, not a database
//   safeguard, and the UI says exactly that. It reads the leading keyword —
//   or, for a `WITH` chain, the first leader of the statement the chain
//   carries — and for UPDATE/DELETE looks for a WHERE at that same level. It
//   therefore flags a DELETE whose only WHERE sits inside a subquery (a false
//   positive that costs one extra confirmation) and cannot see anything the
//   database would do with triggers, rules, or cascading constraints.
//
//   The two judgements must agree about `WITH`: `classifyStatement` calls
//   `WITH gone AS (DELETE ...)` a write, so the pattern check has to see that
//   delete too — as the verb of the CTE body, where it is reported as a
//   mutation inside the clause rather than as an unbounded one.
// =============================================================================

import type { SqlDialect } from '../connect';
import { hasTopLevelKeyword, keywordSites, stripSqlComments } from './split';
import type { IKeywordSite } from './split';

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

/**
 * Keywords that can lead a statement, whether it is the one a `WITH` chain
 * carries or the one inside a CTE body. Whichever comes FIRST in a group is
 * that group's verb, which is how a trailing `FOR UPDATE` or `DO UPDATE` stays
 * what it is: a clause of the SELECT or INSERT that leads the group, not a
 * verb of its own.
 */
const WITH_LEADERS = ['select', 'insert', 'update', 'delete', 'merge', 'values', 'table'];

/**
 * The leaders that are NOT reserved words, so a CTE may be named after one.
 * SELECT, VALUES, TABLE and WITH are reserved and can never be names.
 */
const NAMEABLE_LEADERS = ['insert', 'update', 'delete', 'merge'];

/**
 * The CTE mutations the pattern check names. INSERT/MERGE/REPLACE are absent
 * on purpose: a top-level INSERT is not confirmed either, and one inside a
 * clause is no more destructive than one outside it.
 */
const CTE_MUTATIONS = ['update', 'delete'];

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

/**
 * Whether a depth-0 keyword is a CTE's NAME rather than a statement's verb.
 *
 * PostgreSQL lists INSERT, UPDATE, DELETE and MERGE as non-reserved words, so
 * `WITH merge AS (SELECT 1) DELETE FROM t` is a legal chain whose first
 * depth-0 keyword is the CTE's name. Reading that name as the verb would hide
 * the DELETE behind it, which is the false negative this whole check exists to
 * close.
 *
 * A name is followed by `AS`, or by its column list — `merge (x) AS (...)`.
 * The column-list form is only read as a name for those four words, and it is
 * unambiguous for them because a real statement never puts `(` straight after
 * the verb: it is `INSERT INTO`, `UPDATE t`, `DELETE FROM`, `MERGE INTO`. The
 * reserved words cannot be names at all, so `SELECT (1 + 2)` and `VALUES (1)`
 * stay statements.
 *
 * @param head - The normalised statement.
 * @param site - A keyword occurrence in it.
 * @returns True when the keyword names a CTE.
 */
function namesCte(head: string, site: IKeywordSite): boolean {
	const after = head.slice(site.index + site.keyword.length);
	if (/^\s*as\b/i.test(after)) return true;
	return NAMEABLE_LEADERS.includes(site.keyword) && /^\s*\(/.test(after);
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
 * Look for the statement shapes the confirmation dialog asks about: UPDATE or
 * DELETE with no top-level WHERE, an UPDATE or DELETE inside a WITH clause,
 * TRUNCATE, DROP, ALTER.
 *
 * `EXPLAIN ANALYZE` is checked as the statement it would run, because it runs
 * it: the prefix is peeled here the same way {@link classifyStatement} peels
 * it, which is what keeps the two judgements from disagreeing about a form
 * that empties a table. A plain `EXPLAIN` runs nothing and is never a finding.
 *
 * A `WITH` chain is read group by group, because PostgreSQL lets the statement
 * and any CTE body carry a write. Each parenthesised group has a VERB — its
 * first leader that is not a CTE name — and so does the statement itself. The
 * statement's verb is judged exactly like a bare UPDATE/DELETE; a CTE body
 * whose verb mutates is reported as `<VERB> inside a WITH clause` — never as
 * "without WHERE", because a WHERE inside a body cannot be attributed to that
 * verb by a text check. The outer finding is the more specific one and wins
 * when both apply. INSERT, MERGE and REPLACE inside a CTE are not flagged, for
 * parity with a top-level INSERT, which is not flagged either.
 *
 * Reading the body by its verb rather than by what touches its bracket is what
 * keeps `WITH a AS (WITH b AS (SELECT 1) DELETE FROM t RETURNING *) SELECT 1`
 * — a body with a read-only chain of its own — a DELETE inside a WITH clause.
 *
 * Both rules read POSITION, not presence. `WITH a AS (...) SELECT * FROM a FOR
 * UPDATE` locks rows and writes nothing; an upsert's `ON CONFLICT ... DO
 * UPDATE` belongs to its INSERT. Neither is an unbounded UPDATE, and saying so
 * would spend the dialog's credibility on statements that change nothing.
 *
 * A leader followed by `AS`, or one of the non-reserved four (INSERT, UPDATE,
 * DELETE, MERGE) followed by a column list, is a CTE's NAME and is read past
 * to the real verb behind it (see {@link namesCte}).
 *
 * LIMITS, stated plainly because the dialog does too:
 * - A WHERE inside a string literal or a comment does not count (correct).
 * - A WHERE that exists only inside a subquery or a `USING (...)` clause does
 *   not count either, so such a statement is flagged (extra confirmation).
 * - A WHERE clause that matches every row (`WHERE 1=1`) passes the check.
 * - When a chain holds several CTE mutations only the first one in text order
 *   is named; the rest are not listed.
 * - A group's verb is read from its first leader, so a statement form whose
 *   leader is not in {@link WITH_LEADERS} is not judged at all.
 * - A MERGE is never a finding, at either level, although its actions can
 *   update or delete rows: only the verb that leads a group is read, and a
 *   top-level MERGE is not confirmed either.
 * - Nothing here knows what the database will do with triggers or cascades.
 *
 * @param sql - One statement.
 * @param dialect - The engine dialect.
 * @returns The finding, or null when nothing matched.
 */
export function patternCheck(sql: string, dialect: SqlDialect = 'unknown'): IPatternFinding | null {
	const head = normalize(sql, dialect);
	if (!head) return null;

	// EXPLAIN ANALYZE RUNS the statement it describes, and every call here
	// commits on its own, so the prefix is peeled exactly as
	// `classifyStatement` peels it and the check is made on what would really
	// run. A plain EXPLAIN runs nothing and is never a finding.
	if (/^explain\b/i.test(head)) {
		const prefix = EXPLAIN_PREFIX.exec(head)?.[0] ?? 'explain';
		if (!/\banaly[sz]e\b/i.test(prefix)) return null;
		const inner = head.slice(prefix.length).trim();
		if (!inner || /^explain\b/i.test(inner)) return null;
		return patternCheck(inner, dialect);
	}

	if (/^truncate\b/i.test(head)) return { kind: 'TRUNCATE' };
	if (/^drop\b/i.test(head)) return { kind: 'DROP' };
	if (/^alter\b/i.test(head)) return { kind: 'ALTER' };

	// A `WITH` chain can carry the data-modifying verb itself, and `^` anchors
	// cannot see past it. Every parenthesised group gets the same treatment as
	// the statement: its verb is its FIRST leader that is not a CTE name —
	// POSITION, not presence. `... SELECT * FROM a FOR UPDATE` leads with
	// SELECT and only locks rows, and an upsert's `DO UPDATE` trails its
	// INSERT. Reading any `update` would call both an unbounded UPDATE.
	const leadsWith = /^with\b/i.test(head);
	const verbs = new Map<number, IKeywordSite>();
	if (leadsWith) {
		for (const site of keywordSites(head, WITH_LEADERS, dialect)) {
			if (!namesCte(head, site) && !verbs.has(site.group)) verbs.set(site.group, site);
		}
	}
	// Group -1 is the statement the chain carries.
	const leader = verbs.get(-1)?.keyword ?? null;
	const verb = /^update\b/i.test(head) || leader === 'update'
		? 'UPDATE'
		: /^delete\b/i.test(head) || leader === 'delete'
			? 'DELETE'
			: null;
	// Every CTE body is parenthesised, so in a WITH-led statement a WHERE in
	// code at depth 0 belongs to the main statement and to nothing else.
	if (verb && !hasTopLevelKeyword(head, 'where', dialect)) return { kind: `${verb} without WHERE` };

	// The outer statement is bounded, or there is none. A CTE body can still
	// empty a table on its own, and the outer WHERE does not reach inside it.
	// It is the body's VERB that counts, not a word somewhere inside it, and
	// that verb need not touch the bracket: a CTE body may open with a `WITH`
	// chain of its own before the DELETE it runs. Groups were filled in text
	// order, so the first mutation found is the first one in the statement.
	const mutation = [...verbs.values()].find((site) => site.depth > 0 && CTE_MUTATIONS.includes(site.keyword));
	if (mutation) return { kind: `${mutation.keyword.toUpperCase()} inside a WITH clause` };
	return null;
}
