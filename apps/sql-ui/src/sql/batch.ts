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
// SQL — BATCH RUN MODEL (per-statement outcomes and their wording)
// =============================================================================
//
// Running N statements produces N outcomes, and the node runs each one in its
// OWN transaction (db_instance_base's plain execute wraps a single
// `engine.begin()`), so a batch that fails on statement 3 leaves 1 and 2
// COMMITTED and 4 onward not run. That is the single most important thing the
// UI has to say out loud, so the wording for it lives here, next to the data,
// and is unit-tested rather than assembled inline in a component.
//
// Elapsed time is always called ROUND TRIP: it measures the tool call leaving
// the browser and coming back, which includes queueing and transport. It is
// not the database's execution time and must never be labelled as such.
// =============================================================================

import type { SqlDialect } from '../connect';
import type { StatementKind } from './classify';
import { stripSqlComments } from './split';

// =============================================================================
// TYPES
// =============================================================================

/**
 * How one statement of a batch ended.
 *
 * - `pending` — queued, not started.
 * - `running` — sent, no answer yet.
 * - `rows` — returned a result set.
 * - `affected` — reported an affected-row count.
 * - `error` — the node or the database rejected it.
 * - `abandoned` — the user stopped waiting; it MAY still be running remotely.
 * - `skipped` — an earlier statement failed, so this one was never sent.
 */
export type RunOutcome = 'pending' | 'running' | 'rows' | 'affected' | 'error' | 'abandoned' | 'skipped';

/** One statement of a batch, with whatever is known about it so far. */
export interface IStatementRun {
	/** Zero-based position in the batch. */
	index: number;
	/** The statement as sent (before the row limit is appended). */
	sql: string;
	/** Statement kind, by pattern. */
	kind: StatementKind;
	/** Leading keyword, for the strip label. */
	verb: string;
	/** Start offset in the editor buffer, when the statement came from one. */
	start?: number;
	/** End offset in the editor buffer, when the statement came from one. */
	end?: number;
	/** One-based first line in the editor buffer. */
	startLine: number;
	/** One-based last line in the editor buffer. */
	endLine: number;
	/** Current outcome. */
	outcome: RunOutcome;
	/** Returned rows, when the outcome is `rows`. */
	rows?: Record<string, unknown>[];
	/** Affected-row count, when the outcome is `affected`. */
	affected?: number;
	/** Round-trip milliseconds, once an answer (or an abandonment) landed. */
	ms?: number;
	/** Verbatim failure text, when the outcome is `error`. */
	error?: string;
	/** Row limit appended to this statement, or null when none was. */
	limitApplied?: number | null;
}

// =============================================================================
// WORDING
// =============================================================================

/**
 * The leading keyword of a statement, for the status strip's label.
 *
 * @param sql - The statement text.
 * @param dialect - The engine dialect (comment syntax).
 * @returns The keyword in upper case, or 'SQL' when there is none.
 */
export function leadingVerb(sql: string, dialect: SqlDialect = 'unknown'): string {
	const match = /[A-Za-z_][A-Za-z0-9_]*/.exec(stripSqlComments(sql, dialect).replace(/^[\s(]+/, ''));
	return match ? match[0].toUpperCase() : 'SQL';
}

/**
 * Format a round-trip duration.
 *
 * @param ms - Milliseconds measured in the browser.
 * @returns e.g. `round trip 0.031 s`.
 */
export function formatElapsed(ms: number): string {
	return `round trip ${(ms / 1000).toFixed(3)} s`;
}

/** The four things a batch position can be said to have done. */
type OutcomeGroup = 'committed' | 'failed' | 'not run' | 'abandoned';

/**
 * Which group an outcome belongs to in the batch summary.
 *
 * `committed` is the honest word for a statement that finished: each one ran
 * in its own transaction and is already durable, whether it returned rows or
 * changed them.
 *
 * @param outcome - The statement's outcome.
 * @returns The group, or null for a statement that has not resolved.
 */
function groupOf(outcome: RunOutcome): OutcomeGroup | null {
	if (outcome === 'rows' || outcome === 'affected') return 'committed';
	if (outcome === 'error') return 'failed';
	if (outcome === 'abandoned') return 'abandoned';
	if (outcome === 'skipped' || outcome === 'pending') return 'not run';
	return null;
}

/**
 * Summarise a finished batch in one line, e.g.
 * `1–2 committed · 3 failed · 4–5 not run`.
 *
 * Positions are one-based and consecutive positions in the same group collapse
 * into a range. A statement still running contributes nothing, so the line is
 * only complete once the batch is.
 *
 * @param runs - The batch's statements, in order.
 * @returns The summary line ('' when there is nothing to say).
 */
export function formatBatchOutcome(runs: IStatementRun[]): string {
	const parts: string[] = [];
	let groupStart = -1;
	let groupName: OutcomeGroup | null = null;

	/**
	 * Close the open range and push its phrase.
	 *
	 * @param endIndex - One-based position of the range's last statement.
	 */
	const flush = (endIndex: number): void => {
		if (groupName === null || groupStart < 0) return;
		const span = groupStart === endIndex ? `${groupStart}` : `${groupStart}–${endIndex}`;
		parts.push(`${span} ${groupName}`);
	};

	for (let i = 0; i < runs.length; i++) {
		const group = groupOf(runs[i].outcome);
		if (group === groupName) continue;
		flush(i);
		groupName = group;
		groupStart = group === null ? -1 : i + 1;
	}
	flush(runs.length);
	return parts.join(' · ');
}

/**
 * The status strip's label for one statement, e.g.
 * `2 UPDATE · 3 affected · round trip 0.012 s`.
 *
 * The full text is in the label rather than carried by colour, so the strip's
 * buttons have complete accessible names.
 *
 * @param run - The statement.
 * @returns The label.
 */
export function formatRunLabel(run: IStatementRun): string {
	const head = `${run.index + 1} ${run.verb}`;
	const elapsed = run.ms === undefined ? '' : ` · ${formatElapsed(run.ms)}`;
	switch (run.outcome) {
		case 'rows':
			return `${head} · ${(run.rows?.length ?? 0).toLocaleString()} rows${elapsed}`;
		case 'affected':
			return `${head} · ${(run.affected ?? 0).toLocaleString()} affected${elapsed}`;
		case 'error':
			return `${head} · error${elapsed}`;
		case 'abandoned':
			return `${head} · abandoned${elapsed}`;
		case 'running':
			return `${head} · running…`;
		case 'skipped':
			return `${head} · not run`;
		default:
			return `${head} · queued`;
	}
}

// =============================================================================
// ROW LIMIT
// =============================================================================

/**
 * Row-returning statements: SELECT, a parenthesised set expression, and
 * read-only WITH chains. A data-modifying CTE (`WITH ... INSERT/UPDATE/DELETE`)
 * is NOT one — appending LIMIT there is invalid SQL.
 */
const RETURNS_ROWS = /^select\b/i;

/**
 * Append the header's row limit to a statement that returns rows.
 *
 * A statement that already carries its own LIMIT is left alone: the user's
 * limit governs, and the meta line reports that none was applied by the app.
 * Nothing is appended to writes, DDL, SHOW, EXPLAIN or DESCRIBE, where the
 * clause is either invalid or silently changes what the statement does.
 *
 * @param sql - The statement.
 * @param limit - The header selection ('200', '1000' or 'All').
 * @param dialect - The engine dialect (comment syntax).
 * @returns The statement to send and the limit that was appended (null when
 *          none was).
 */
export function applyRowLimit(sql: string, limit: string, dialect: SqlDialect = 'unknown'): { sql: string; limit: number | null } {
	if (limit === 'All') return { sql, limit: null };
	const value = Number(limit);
	if (!Number.isFinite(value) || value <= 0) return { sql, limit: null };
	const stripped = stripSqlComments(sql, dialect).replace(/;\s*$/, '').trim();
	const bare = stripped.replace(/^[\s(]+/, '');
	const returnsRows = RETURNS_ROWS.test(bare)
		|| stripped.startsWith('(')
		|| (/^with\b/i.test(bare) && !/\b(insert|update|delete|merge|replace)\b/i.test(bare));
	if (!returnsRows) return { sql, limit: null };
	if (/\blimit\b/i.test(bare)) return { sql, limit: null };
	return { sql: `${sql.replace(/;\s*$/, '').trimEnd()} LIMIT ${value}`, limit: value };
}
