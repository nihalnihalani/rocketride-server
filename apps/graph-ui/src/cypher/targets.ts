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
// CYPHER - WHAT RUN SENDS (selection, caret statement, or everything)
// =============================================================================
//
// Run (Ctrl/Cmd+Enter) sends the selection when there is one - split into its
// statements, because a drag can cover several - otherwise the statement the
// caret is in. Run all (Ctrl/Cmd+Shift+Enter) sends every statement in order.
// What a press WOULD send is named in text under the editor before the key is
// pressed: a highlight alone is not an answer for anyone who cannot see it.
// =============================================================================

import { splitStatements, splitStatementsIn, statementAtOffset } from './split';
import type { IStatement } from './split';
import type { IRunTarget } from 'shared/explorer';

/** The editor's selection, as offsets (equal when nothing is selected). */
export interface ISelection {
	start: number;
	end: number;
}

/**
 * A statement as the shared runner takes it.
 *
 * @param statement - A statement from the splitter.
 * @returns The run target.
 */
function toTarget(statement: IStatement): IRunTarget {
	return { text: statement.text, start: statement.start, end: statement.end, startLine: statement.startLine, endLine: statement.endLine };
}

/**
 * What a run would send.
 *
 * @param buffer - The editor text.
 * @param selection - The selection (start === end when empty).
 * @param caret - The caret offset.
 * @param all - True for Run all.
 * @returns The statements, in order (possibly none).
 */
export function targetsToRun(buffer: string, selection: ISelection, caret: number, all: boolean): IRunTarget[] {
	if (all) return splitStatements(buffer).map(toTarget);
	if (selection.end > selection.start) return splitStatementsIn(buffer, selection.start, selection.end).map(toTarget);
	const at = statementAtOffset(buffer, caret);
	return at ? [toTarget(at)] : [];
}

/**
 * The "Will run" sentence for the text under the editor.
 *
 * @param buffer - The editor text.
 * @param selection - The selection.
 * @param caret - The caret offset.
 * @returns A sentence naming what Run would send.
 */
export function describeRun(buffer: string, selection: ISelection, caret: number): string {
	const targets = targetsToRun(buffer, selection, caret, false);
	if (targets.length === 0) return 'Nothing to run.';
	const lines = (t: IRunTarget): string => (t.startLine === undefined ? '' : t.startLine === t.endLine ? `line ${t.startLine}` : `lines ${t.startLine}–${t.endLine}`);
	const selected = selection.end > selection.start;
	if (targets.length === 1) return `Will run: ${selected ? 'the selection' : 'the statement'} at ${lines(targets[0])}.`;
	const first = targets[0];
	const last = targets[targets.length - 1];
	return `Will run: ${targets.length} statements from the selection (lines ${first.startLine}–${last.endLine}), in order, stopping at the first error.`;
}
