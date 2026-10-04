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
// GRAPH - FAILURE NOTICES (what the banner says for each way a call can fail)
// =============================================================================
//
// The shared tool session turns every failure into one error with a `kind`; this
// module decides what the user reads. The banner leads with the first line of the
// node's message (the headline) and shows the rest under "Database said", exactly
// as SQL Explorer does, and adds ONE hint where the app knows what to do next.
//
//   Refused: ...                 the read path refused a write. Writes go through
//                                the write console, only where the node allows
//                                execute.
//   Not supported on Apache AGE  an AGE limit the node explains; its own text is
//                                the hint.
//   timeout                      this app stopped waiting; the database may still
//                                be running the query and nothing here can cancel it.
//   upgrade                      the node lacks read_query (or the tool): never
//                                a fallback to another tool.
//   malformed                    the node answered in a shape this app does not
//                                understand.
//   stale                        dropped: a newer request replaced this one, and the
//                                user never sees it.
// =============================================================================

import { GRID_NOTICE, STOP_WAITING_NOTE, UPGRADE_READ_QUERY } from './wording';

/** What the shared tool session threw, reduced to what this module reads. */
export interface IFailureInput {
	kind: string;
	tool: string;
	/** The full message, verbatim. */
	message: string;
	/** First line of the message. */
	headline: string;
	/** Everything after the first line. */
	detail?: string;
	code?: string;
}

/** A failure as the banner shows it. */
export interface IFailureNotice {
	/** `error` for a failure, `info` for a notice that is not the user's fault. */
	variant: 'error' | 'warning' | 'info';
	headline: string;
	/** The node's text under "Database said". */
	detail: string;
	/** One sentence on what to do next, or null. */
	hint: string | null;
	/** True when the result of this call must not be shown at all. */
	ignore: boolean;
}

/** The label above the node's own text. */
export const DATABASE_SAID_LABEL = 'Database said';

/** The legacy refusal text of a node that has `execute` off (a plain error, no code). */
const LEGACY_EXECUTE_OFF = /execute tool is disabled for this node/i;

/** The engine's text when it does not know a tool. */
const UNKNOWN_TOOL = /no handler found for tool/i;

/**
 * Describe a failed call for the banner.
 *
 * @param error - The failure.
 * @param canWrite - Whether this endpoint shows a write console (execute allowed).
 * @returns The notice.
 */
export function describeFailure(error: IFailureInput, canWrite: boolean): IFailureNotice {
	if (error.kind === 'stale') return { variant: 'info', headline: '', detail: '', hint: null, ignore: true };
	const base = { detail: error.detail ?? '', ignore: false };

	if (error.kind === 'upgrade' || UNKNOWN_TOOL.test(error.message)) return { variant: 'warning', headline: UPGRADE_READ_QUERY, detail: '', hint: null, ignore: false };
	if (LEGACY_EXECUTE_OFF.test(error.message)) {
		return { ...base, variant: 'error', headline: 'This node does not allow execute (allow_execute is off).', detail: '', hint: 'Browsing with Cypher works. Statements that change data need a node with direct execution turned on.' };
	}
	if (error.kind === 'timeout') return { ...base, variant: 'warning', headline: error.headline, detail: error.detail ?? '', hint: STOP_WAITING_NOTE };
	if (error.kind === 'unavailable') return { ...base, variant: 'error', headline: error.headline, hint: 'Start the pipeline, then refresh the connections.' };
	if (error.kind === 'malformed') return { ...base, variant: 'error', headline: error.headline, hint: 'The node answered in a shape this app does not understand. It may need an upgrade.' };
	if (error.kind === 'invalid') return { ...base, variant: 'error', headline: error.headline, hint: null };

	if (/^Refused:/i.test(error.headline)) {
		return { ...base, variant: 'error', headline: error.headline, hint: canWrite ? 'To change data, use the write console for this connection.' : 'Browsing is read-only. To change data, use a node with direct execution turned on.' };
	}
	if (/^Not supported on Apache AGE/i.test(error.headline)) return { ...base, variant: 'error', headline: error.headline, hint: 'Apache AGE 1.5.0 does not support this Cypher construct; rewrite the query without it.' };
	if (/^Query timed out/i.test(error.headline)) return { ...base, variant: 'warning', headline: error.headline, hint: 'The node stopped the query. Narrow it, or lower the row limit.' };
	if (/^Invalid read_query input/i.test(error.headline)) return { ...base, variant: 'error', headline: error.headline, hint: null };
	return { ...base, variant: 'error', headline: error.headline || error.message, hint: null };
}

/** Re-exported so the canvas notice and the failure strip share one place for their wording. */
export { GRID_NOTICE };
