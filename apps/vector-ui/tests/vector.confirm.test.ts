// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CONFIRM AND REMOVE: what the dialogs say, typed confirmations, batches that stop at the first error
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ExplorerToolError } from 'shared/explorer';
import { MULTI_REMOVE_LIST_MAX } from '../src/vector/budgets';
import { REMOVE_CANCEL_LABEL, batches, confirmReady, multiRemoveConfirmation, removalSummary, removeConfirmation, runRemoval } from '../src/vector/confirm';
import type { IRemoveContext } from '../src/vector/confirm';
import type { IRemoveView } from '../src/vector/results';
import { CODE_SENTENCES } from '../src/vector/wording';

const PG: IRemoveContext = { storeName: 'PostgreSQL (pgvector)', collection: 'vx_demo_docs', backend: 'pgvector', provider: 'postgres' };
const RRV: IRemoveContext = { storeName: 'RocketRide Vector', collection: 'vector_explorer_docs', backend: 'pgvector', provider: 'rocketride_vector' };
const KESTREL = { objectId: 'kestrel-guide-object-id', path: 'C:/demo/field/kestrel_field_guide.md', chunks: 12 };

test('the single-document dialog: path, short objectId, chunk count, where, and what cannot be undone', () => {
	const c = removeConfirmation(KESTREL, PG);
	assert.equal(c.title, 'Remove this document?');
	assert.deepEqual(c.lines, [
		{ label: 'Path', value: 'C:/demo/field/kestrel_field_guide.md' },
		{ label: 'objectId', value: 'kestrel-…' },
		{ label: 'Chunks', value: '12' },
		{ label: 'Store', value: 'PostgreSQL (pgvector) · vx_demo_docs · pgvector' },
	]);
	assert.equal(c.sentence, 'Removes this document and its 12 chunks from vx_demo_docs. This cannot be undone; add the file again to restore it.');
	assert.equal(c.confirmLabel, 'Remove document');
	assert.equal(c.cancelLabel, REMOVE_CANCEL_LABEL);
	assert.equal(REMOVE_CANCEL_LABEL, 'Cancel');
	assert.equal(c.typed, null, 'a store of its own needs no typed confirmation');
	assert.equal(removeConfirmation({ ...KESTREL, chunks: null }, PG).sentence, 'Removes this document and all its chunks from vx_demo_docs. This cannot be undone; add the file again to restore it.', 'no invented count');
	assert.equal(removeConfirmation({ ...KESTREL, chunks: 1 }, PG).sentence.includes('its 1 chunk from'), true);
});

test('rocketride_vector: type the table name, and say the table is shared by the organization', () => {
	const c = removeConfirmation(KESTREL, RRV);
	assert.deepEqual(c.typed, { expected: 'vector_explorer_docs', prompt: "Type the table name 'vector_explorer_docs' to confirm." });
	assert.ok(c.extra.includes("Shared table: every pipeline in this organization that names table 'vector_explorer_docs' reads and writes these rows."));
	assert.equal(confirmReady(c.typed, 'vector_explorer_docs'), true);
	assert.equal(confirmReady(c.typed, ' vector_explorer_docs '), true);
	assert.equal(confirmReady(c.typed, 'VECTOR_EXPLORER_DOCS'), false);
	assert.equal(confirmReady(null, ''), true);
});

test('the multi-remove dialog: type the count, at most 20 paths listed, the rest counted', () => {
	const targets = Array.from({ length: 23 }, (_, i) => ({ objectId: `id-${i}`, path: `C:/demo/f${i}.md`, chunks: 2 }));
	const c = multiRemoveConfirmation(targets, PG);
	assert.equal(c.title, 'Remove 23 documents?');
	assert.equal(c.listed.length, MULTI_REMOVE_LIST_MAX);
	assert.equal(c.more, 3);
	assert.deepEqual(c.typed, { expected: '23', prompt: 'Type 23 to confirm.' });
	assert.equal(c.confirmLabel, 'Remove 23 documents');
	assert.equal(c.sentence, 'Removes these 23 documents and their 46 chunks from vx_demo_docs, in batches of at most 100; the first error stops the rest. This cannot be undone.');
	const shared = multiRemoveConfirmation(targets.slice(0, 2), RRV);
	assert.equal(shared.typed?.expected, 'vector_explorer_docs', 'on a shared table the table name is typed, not the count');
	assert.equal(multiRemoveConfirmation([...targets.slice(0, 1), { objectId: 'x', path: 'x', chunks: null }], PG).sentence.includes('and all their chunks'), true);
});

test("batches of at most 100 (the node's write_ids_max)", () => {
	const ids = Array.from({ length: 250 }, (_, i) => `id-${i}`);
	assert.deepEqual(
		batches(ids, 100).map((b) => b.length),
		[100, 100, 50]
	);
	assert.deepEqual(batches([], 100), []);
	assert.deepEqual(batches(['a'], 0), [['a']], 'a nonsense size still sends one id per batch');
});

test('runRemoval: every batch in order, rows as the node reported them', async () => {
	const sent: string[][] = [];
	const outcome = await runRemoval(
		['a', 'b', 'c'],
		async (batch) => {
			sent.push(batch);
			return { removed: batch.filter((id) => id !== 'c').map((objectId) => ({ objectId, chunks: 2 })), notFound: batch.filter((id) => id === 'c'), removedChunks: 2 * batch.filter((id) => id !== 'c').length } satisfies IRemoveView;
		},
		2
	);
	assert.deepEqual(sent, [['a', 'b'], ['c']]);
	assert.deepEqual(
		outcome.removed.map((r) => r.objectId),
		['a', 'b']
	);
	assert.deepEqual(outcome.notFound, ['c']);
	assert.equal(outcome.removedChunks, 4);
	assert.equal(outcome.batchesRun, 2);
	assert.equal(outcome.batchesTotal, 2);
	assert.equal(outcome.error, null);
});

test('runRemoval stops at the first error and says what already ran; a count the node did not give stays unknown', async () => {
	const sent: string[][] = [];
	const outcome = await runRemoval(
		['a', 'b', 'c', 'd'],
		async (batch) => {
			sent.push(batch);
			if (batch[0] === 'c') throw new ExplorerToolError({ kind: 'store', tool: 'remove_document', message: 'Removing documents is turned off', code: 'WRITES_DISABLED' });
			return { removed: batch.map((objectId) => ({ objectId, chunks: null })), notFound: [], removedChunks: null };
		},
		2
	);
	assert.deepEqual(
		sent,
		[
			['a', 'b'],
			['c', 'd'],
		],
		'nothing after the failed batch is sent'
	);
	assert.equal(outcome.batchesRun, 1);
	assert.equal(outcome.removedChunks, null);
	assert.deepEqual(outcome.error, { headline: CODE_SENTENCES.WRITES_DISABLED });
	assert.equal(removalSummary(outcome, [{ objectId: 'a', path: 'a.md' }]), `Removed 2 documents. Stopped after 1 of 2 batches: ${CODE_SENTENCES.WRITES_DISABLED}`);
});

test('the announcement after a removal names the document and the rows removed', () => {
	const one = { removed: [{ objectId: 'k', chunks: 12 }], notFound: [], removedChunks: 12, batchesRun: 1, batchesTotal: 1, error: null };
	assert.equal(removalSummary(one, [{ objectId: 'k', path: 'C:/demo/field/kestrel_field_guide.md' }]), 'Removed C:/demo/field/kestrel_field_guide.md (12 chunks)');
	const gone = { removed: [], notFound: ['k'], removedChunks: 0, batchesRun: 1, batchesTotal: 1, error: null };
	assert.equal(removalSummary(gone, [{ objectId: 'k', path: 'x.md' }]), 'x.md was not stored any more; nothing was removed');
	const many = {
		removed: [
			{ objectId: 'a', chunks: 1 },
			{ objectId: 'b', chunks: 2 },
		],
		notFound: ['c'],
		removedChunks: 3,
		batchesRun: 1,
		batchesTotal: 1,
		error: null,
	};
	assert.equal(removalSummary(many, []), 'Removed 2 documents (3 chunks). 1 was not stored any more.');
	const timeout = { removed: [], notFound: [], removedChunks: null, batchesRun: 0, batchesTotal: 1, error: { headline: 'The request may still complete on the server. Refresh to check.' } };
	assert.equal(removalSummary(timeout, [{ objectId: 'k', path: 'x.md' }]), 'The request may still complete on the server. Refresh to check.');
});
