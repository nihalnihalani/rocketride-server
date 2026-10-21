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
// VECTOR - CONFIRM AND REMOVE (pure): what the dialogs say, and the batched removal
// =============================================================================
//
// Removing a document is the console's one write. It follows Graph
// Explorer's rules: the dialog is destructive, its Cancel has the focus (so a
// stray Enter cancels), Cancel sends nothing, and the text says exactly what
// will go: the path, a short objectId, the chunk count the store reported
// (never an estimate), and where. On `rocketride_vector` the table is shared
// by every pipeline of the organization that names it, so the user types the
// table name. Several documents are confirmed by typing their count, sent in
// batches of at most `write_ids_max` (100), and the first error stops the
// rest; the summary says what already ran.
// =============================================================================

import { MULTI_REMOVE_LIST_MAX } from './budgets';
import type { IRemoveView } from './results';
import { formatCount } from './stats';
import { failureText } from './wording';
import type { IFailureText } from './wording';

/** The dialogs' cancel label (the focus step looks for it). */
export const REMOVE_CANCEL_LABEL = 'Cancel';

/** A document to remove. */
export interface IRemoveTarget {
	objectId: string;
	path: string;
	/** Chunks the store reported for it, or null. */
	chunks: number | null;
}

/** Where the documents are removed from. */
export interface IRemoveContext {
	/** The store node's display name. */
	storeName: string;
	collection: string | null;
	backend: string;
	provider: string;
}

/** A typed confirmation: the confirm button stays disabled until the input equals `expected`. */
export interface ITypedConfirmation {
	expected: string;
	prompt: string;
}

/** What the single-document dialog shows. */
export interface IRemoveConfirmation {
	title: string;
	lines: Array<{ label: string; value: string }>;
	sentence: string;
	/** Further sentences (the shared-table warning). */
	extra: string[];
	confirmLabel: string;
	cancelLabel: string;
	typed: ITypedConfirmation | null;
}

/** What the multi-remove dialog shows. */
export interface IMultiRemoveConfirmation {
	title: string;
	/** Up to MULTI_REMOVE_LIST_MAX paths. */
	listed: string[];
	/** How many more are not listed. */
	more: number;
	sentence: string;
	extra: string[];
	confirmLabel: string;
	cancelLabel: string;
	typed: ITypedConfirmation;
}

/**
 * The shared-table sentence of `rocketride_vector`.
 *
 * @param table - The table name.
 * @returns The sentence.
 */
export function sharedTableSentence(table: string): string {
	return `Shared table: every pipeline in this organization that names table '${table}' reads and writes these rows.`;
}

/** The collection's name as the dialogs say it. */
function collectionName(ctx: IRemoveContext): string {
	return ctx.collection ?? 'this collection';
}

/** The typed table-name confirmation of a shared table, or null. */
function sharedTyped(ctx: IRemoveContext): ITypedConfirmation | null {
	if (ctx.provider !== 'rocketride_vector') return null;
	const table = collectionName(ctx);
	return { expected: table, prompt: `Type the table name '${table}' to confirm.` };
}

/**
 * The single-document dialog.
 *
 * @param target - The document.
 * @param ctx - Where it is stored.
 * @returns What the dialog shows.
 */
export function removeConfirmation(target: IRemoveTarget, ctx: IRemoveContext): IRemoveConfirmation {
	const collection = collectionName(ctx);
	const chunks = target.chunks === null ? 'all its chunks' : `its ${formatCount(target.chunks)} ${target.chunks === 1 ? 'chunk' : 'chunks'}`;
	const typed = sharedTyped(ctx);
	return {
		title: 'Remove this document?',
		lines: [
			{ label: 'Path', value: target.path || '(no path)' },
			{ label: 'objectId', value: `${target.objectId.slice(0, 8)}…` },
			{ label: 'Chunks', value: target.chunks === null ? '—' : formatCount(target.chunks) },
			{ label: 'Store', value: [ctx.storeName, ctx.collection, ctx.backend].filter(Boolean).join(' · ') },
		],
		sentence: `Removes this document and ${chunks} from ${collection}. This cannot be undone; add the file again to restore it.`,
		extra: typed ? [sharedTableSentence(collection)] : [],
		confirmLabel: 'Remove document',
		cancelLabel: REMOVE_CANCEL_LABEL,
		typed,
	};
}

/**
 * The multi-remove dialog.
 *
 * @param targets - The documents.
 * @param ctx - Where they are stored.
 * @returns What the dialog shows.
 */
export function multiRemoveConfirmation(targets: readonly IRemoveTarget[], ctx: IRemoveContext): IMultiRemoveConfirmation {
	const n = targets.length;
	const collection = collectionName(ctx);
	const known = targets.every((t) => t.chunks !== null);
	const chunks = known ? `their ${formatCount(targets.reduce((sum, t) => sum + (t.chunks ?? 0), 0))} chunks` : 'all their chunks';
	const shared = sharedTyped(ctx);
	return {
		title: `Remove ${formatCount(n)} documents?`,
		listed: targets.slice(0, MULTI_REMOVE_LIST_MAX).map((t) => t.path || '(no path)'),
		more: Math.max(0, n - MULTI_REMOVE_LIST_MAX),
		sentence: `Removes these ${formatCount(n)} documents and ${chunks} from ${collection}, in batches of at most 100; the first error stops the rest. This cannot be undone.`,
		extra: shared ? [sharedTableSentence(collection)] : [],
		confirmLabel: `Remove ${formatCount(n)} documents`,
		cancelLabel: REMOVE_CANCEL_LABEL,
		typed: shared ?? { expected: String(n), prompt: `Type ${n} to confirm.` },
	};
}

/**
 * Whether a typed confirmation is satisfied.
 *
 * @param typed - The confirmation, or null when none is needed.
 * @param input - What the user typed.
 * @returns True when the confirm button may be enabled.
 */
export function confirmReady(typed: ITypedConfirmation | null, input: string): boolean {
	return typed === null || input.trim() === typed.expected;
}

// =============================================================================
// THE REMOVAL
// =============================================================================

/**
 * Split ids into batches.
 *
 * @param ids - The objectIds.
 * @param size - The node's write_ids_max.
 * @returns The batches, in order.
 */
export function batches(ids: readonly string[], size: number): string[][] {
	const step = Math.max(1, Math.floor(size));
	const out: string[][] = [];
	for (let i = 0; i < ids.length; i += step) out.push(ids.slice(i, i + step));
	return out;
}

/** What a removal did. */
export interface IRemovalOutcome {
	removed: Array<{ objectId: string; chunks: number | null }>;
	notFound: string[];
	/** Rows removed in total, or null when any batch could not count them. */
	removedChunks: number | null;
	batchesRun: number;
	batchesTotal: number;
	/** Why it stopped, when a batch failed. */
	error: IFailureText | null;
}

/**
 * Remove documents batch by batch, stopping at the first error. Never retried.
 *
 * @param ids - The objectIds.
 * @param call - Sends one batch (`remove_document`) and reads its answer.
 * @param size - The batch size (the node's write_ids_max).
 * @returns What ran.
 */
export async function runRemoval(ids: readonly string[], call: (batch: string[]) => Promise<IRemoveView>, size: number): Promise<IRemovalOutcome> {
	const all = batches(ids, size);
	const outcome: IRemovalOutcome = { removed: [], notFound: [], removedChunks: 0, batchesRun: 0, batchesTotal: all.length, error: null };
	for (const batch of all) {
		try {
			const view = await call(batch);
			outcome.removed.push(...view.removed);
			outcome.notFound.push(...view.notFound);
			outcome.removedChunks = outcome.removedChunks === null || view.removedChunks === null ? null : outcome.removedChunks + view.removedChunks;
			outcome.batchesRun += 1;
		} catch (error) {
			outcome.error = failureText(error, { write: true }) ?? { headline: 'The removal was dropped.' };
			break;
		}
	}
	return outcome;
}

/**
 * The sentence announced (and shown) after a removal.
 *
 * @param outcome - What ran.
 * @param targets - The documents asked for (their paths name a single removal).
 * @returns The sentence.
 */
export function removalSummary(outcome: IRemovalOutcome, targets: ReadonlyArray<{ objectId: string; path: string }>): string {
	const rows = outcome.removedChunks === null ? '' : ` (${formatCount(outcome.removedChunks)} ${outcome.removedChunks === 1 ? 'chunk' : 'chunks'})`;
	const stopped = outcome.error ? ` Stopped after ${outcome.batchesRun} of ${outcome.batchesTotal} batches: ${outcome.error.headline}` : '';
	if (outcome.removed.length === 0 && outcome.notFound.length === 0) return outcome.error ? outcome.error.headline : 'Nothing was removed.';
	if (targets.length === 1 && outcome.removed.length <= 1 && !outcome.error) {
		const path = targets[0].path || targets[0].objectId;
		return outcome.removed.length === 1 ? `Removed ${path}${rows}` : `${path} was not stored any more; nothing was removed`;
	}
	const gone = outcome.notFound.length === 0 ? '' : ` ${formatCount(outcome.notFound.length)} ${outcome.notFound.length === 1 ? 'was' : 'were'} not stored any more.`;
	const removedRows = outcome.error && outcome.removedChunks === null ? '' : rows;
	return `Removed ${formatCount(outcome.removed.length)} ${outcome.removed.length === 1 ? 'document' : 'documents'}${removedRows}.${gone}${stopped}`;
}
