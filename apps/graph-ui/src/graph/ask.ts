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
// GRAPH - ASK A QUESTION (get_query: a preview the user runs, or prose)
// =============================================================================
//
// `get_query` asks the node's language model to write Cypher. Three answers:
//
//   { query, valid: true }     Cypher the node already vetted as read-only: a
//                              PREVIEW. The app puts it in the editor and does
//                              NOT run it; the user presses Run.
//   { answer, valid: false }   the model answered in prose (the question was not
//                              about the graph). That is an answer, not an error.
//   { error, valid: false }    the node could not produce a safe query. A failure.
//
// A pipeline without a language model cannot answer at all. Browsing with Cypher
// still works, so Ask shows an "unavailable" state instead of an error banner,
// and says why. Generated Cypher never runs automatically.
// =============================================================================

import { isPlainObject } from './values';

/** What a `get_query` answer means. */
export type AskAnswer = { kind: 'cypher'; cypher: string } | { kind: 'prose'; text: string };

/**
 * Read a `get_query` answer that passed the shared result check.
 *
 * @param value - The tool's resolved value.
 * @returns The answer, or null when it is neither Cypher nor prose.
 */
export function readAskAnswer(value: unknown): AskAnswer | null {
	if (!isPlainObject(value)) return null;
	if (value.valid === true && typeof value.query === 'string' && value.query.trim() !== '') return { kind: 'cypher', cypher: value.query.trim() };
	if (value.valid === false && typeof value.answer === 'string' && value.answer.trim() !== '') return { kind: 'prose', text: value.answer.trim() };
	return null;
}

/** A failed question, explained. */
export interface IAskFailure {
	headline: string;
	detail: string;
	/** True when the failure looks like the pipeline has no language model. */
	unavailable: boolean;
}

/** Text in a failure that points at a missing or unconfigured language model. */
const NO_MODEL = /\bllm\b|language model|no model|model (is )?(not|un)(configured|available|connected)|not connected|no (chat|llm) (node|connection)|invoke\.llm|nothing (is )?connected/i;

/**
 * Explain a failed `get_query`.
 *
 * @param error - The failure: a raised error or a `{valid:false, error}` envelope, as headline and detail.
 * @returns The explanation, with `unavailable` set when the pipeline looks to have no model.
 */
export function explainAskFailure(error: { kind: string; headline: string; detail?: string }): IAskFailure {
	const detail = error.detail ?? '';
	// Only a raised error can mean "no model": an `invalid` verdict is the model's own refusal to write a safe query.
	const unavailable = error.kind === 'raised' && NO_MODEL.test(`${error.headline}\n${detail}`);
	return { headline: error.headline, detail, unavailable };
}
