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
// GRAPH - RUN CONFIGURATION (what one statement becomes on its way to the node)
// =============================================================================
//
// Pure helpers the workbench's statement runner is configured with. Nothing here
// talks to the node.
//
//   prepare   cleans a statement (the splitter's text, without its semicolon),
//             classifies it, and fixes the row limit that travels as the
//             `limit` input of `read_query`. The app NEVER appends LIMIT to the
//             user's Cypher and never rewrites it.
//   route     a `read` statement goes to `read_query`; a `write` statement is
//             refused in the browse editor (the write console is the only path to
//             `execute`), and an empty statement is skipped.
//   history   one entry per finished statement: its text, timing, count, outcome
//             and the user's note. Never a token, a DSN or a result.
// =============================================================================

import { classifyStatement, patternCheck } from '../cypher/classify';
import { splitStatements } from '../cypher/split';
import type { IPatternFinding, StatementKind } from '../cypher/classify';
import type { IHistoryEntry } from 'shared/explorer';
import { rowLimitFor } from './dialect';
import type { IGraphDialect } from './dialect';

/** A statement ready to send. */
export interface IPreparedStatement {
	/** The Cypher to send, exactly as the user wrote it (a trailing `;` removed). */
	cypher: string;
	/** The row limit that travels as the `limit` input. */
	limit: number;
	kind: StatementKind;
	/** Leading verb, for labels. */
	verb: string;
	/** What the text check found, for a write. */
	finding: IPatternFinding | null;
}

/**
 * Prepare one statement.
 *
 * @param text - The splitter's statement text.
 * @param limitChoice - 200, 1000, or null for All.
 * @param dialect - The parsed dialect, or null before the probe.
 * @returns The prepared statement.
 */
export function prepareStatement(text: string, limitChoice: number | null, dialect: IGraphDialect | null): IPreparedStatement {
	// The splitter knows which semicolons end a statement (one inside a comment or a string does not).
	const parts = splitStatements(text);
	const cypher = parts.length === 1 ? parts[0].text : text.trim();
	const classification = classifyStatement(cypher);
	return { cypher, limit: rowLimitFor(limitChoice, dialect), kind: classification.kind, verb: classification.verb, finding: patternCheck(cypher) };
}

/**
 * Whether the browse editor may send a batch. A statement that is not a read is
 * refused HERE, before anything is sent, with a message; the node's own read
 * path would refuse it too, and the database role is the boundary either way.
 *
 * @param statements - The prepared statements.
 * @param canWrite - Whether this endpoint has a write console.
 * @returns A refusal message, or null when every statement is a read.
 */
export function refuseNonReads(statements: readonly IPreparedStatement[], canWrite: boolean): string | null {
	const bad = statements.find((s) => s.kind === 'write');
	if (!bad) return null;
	const what = bad.finding ? bad.finding.kind : bad.verb;
	return `This editor only reads. Statement ${statements.indexOf(bad) + 1} looks like it changes data or runs a command (${what}). ${canWrite ? 'Use the write console for this connection.' : 'This node has direct execution turned off, so there is no write console; use a node that allows it.'} This is a text check, not a database safeguard.`;
}

/** The outcome of one run, as history stores it. */
export interface IRunSummary {
	cypher: string;
	at: number;
	ms: number;
	outcome: 'rows' | 'affected' | 'error' | 'abandoned';
	rows?: number;
	affected?: number;
	limit?: number;
	error?: string;
	kind: string;
}

/**
 * The history entry for a finished statement.
 *
 * @param run - What happened.
 * @param id - A unique id for the entry.
 * @returns The entry (text field `cypher`; nothing else of the call).
 */
export function toHistoryEntry(run: IRunSummary, id: string): IHistoryEntry<'cypher'> {
	const entry: IHistoryEntry<'cypher'> = { id, at: run.at, ms: Math.max(0, Math.round(run.ms)), outcome: run.outcome, kind: run.kind || 'OTHER', cypher: run.cypher };
	if (run.rows !== undefined) entry.rows = run.rows;
	if (run.affected !== undefined) entry.affected = run.affected;
	if (run.limit !== undefined) entry.limit = run.limit;
	if (run.error !== undefined) entry.error = run.error;
	return entry;
}
