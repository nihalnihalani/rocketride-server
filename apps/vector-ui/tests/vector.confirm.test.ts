// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CONFIRM AND REMOVE: what the dialogs say, typed confirmations, batches that stop at the first error
// =============================================================================
//
// The map's duplicates queue removes through the same path: its queued
// documents reach the console's multi-remove dialog whole (typed count, the
// paths listed), and the confirmed removal sends them in batches of the
// node's write_ids_max, nothing before Confirm and nothing after Cancel.
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ExplorerToolError } from 'shared/explorer';
import { manualClock } from 'shared/explorer/connect/testing';
import { requestRemoval } from '../src/components/DuplicatesPanel';
import type { IDocumentItem } from '../src/contract/types';
import { dedupeView, docInfo, queueInit, queueReducer, queued } from '../src/map/dedupe';
import { MULTI_REMOVE_LIST_MAX } from '../src/vector/budgets';
import { createConsoleStore } from '../src/vector/consoleStore';
import type { IConsoleDeps } from '../src/vector/consoleStore';
import { readChunksPage, readDocumentsPage, readDeleteResult, readStats } from '../src/vector/results';
import { loadSample } from './support/map.samples';
import { fixture } from './support/fixtures';
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
			return { removed: batch.filter((id) => id !== 'c').map((objectId) => ({ objectId, chunks: 2 })), notFound: batch.filter((id) => id === 'c'), keptLive: [], removedChunks: 2 * batch.filter((id) => id !== 'c').length } satisfies IRemoveView;
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
			if (batch[0] === 'c') throw new ExplorerToolError({ kind: 'store', tool: 'delete', message: 'Removing documents is turned off', code: 'WRITES_DISABLED' });
			return { removed: batch.map((objectId) => ({ objectId, chunks: null })), notFound: [], keptLive: [], removedChunks: null };
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

// =============================================================================
// THE DUPLICATES QUEUE THROUGH THE CONSOLE'S DIALOG
// =============================================================================

/** The demo sample's queue with a document kept by hand in each group, with directory rows for every document of the sample. */
function demoQueue(): { ids: string[]; rows: IDocumentItem[] } {
	const sample = loadSample('sample_demo_1000.json');
	const rows: IDocumentItem[] = sample.docs.map((d) => ({ objectId: d.objectId, path: d.path, chunks: d.chunks, has_first_chunk: true, tables: 0, deleted: false, nodeId: null, size: null, modifyTime: null, ingestedAt: null, pointId: null }));
	const view = dedupeView(sample, 0.97);
	// The demo's groups are shared passages, which a policy leaves alone: keep the first document of each by hand.
	const state = view.groups.reduce((s, g) => queueReducer(s, { type: 'keep', group: g.key, objectId: g.objectIds[0] as string }), queueInit());
	return { ids: queued(view.groups, state, docInfo(sample, rows), new Set()).objectIds, rows };
}

/** A console controller whose removals are recorded batch by batch. */
function consoleWith(rows: IDocumentItem[], writeBatch: number) {
	const sent: string[][] = [];
	const clock = manualClock(Date.parse('2026-10-15T09:00:00Z'));
	const deps: IConsoleDeps = {
		stats: async () => readStats(fixture('stats_pgvector')),
		documents: async () => readDocumentsPage({ ...fixture('list_documents_page2_last'), items: rows }),
		chunks: async () => readChunksPage(fixture('chunks_page')),
		remove: async (ids) => {
			sent.push([...ids]);
			return readDeleteResult({ ...fixture('delete_ok'), removed_chunks: 3 * ids.length }, ids);
		},
		announce: () => undefined,
		clock,
	};
	const store = createConsoleStore(deps, { pageSize: 500, chunkPage: 100, writeBatch });
	store.setWritesEnabled(true);
	return { store, sent };
}

test('the queued duplicates reach the multi-remove dialog whole: typed count, their paths, nothing sent before Confirm', () => {
	const { ids, rows } = demoQueue();
	assert.equal(ids.length, 5, 'the four-document group queues three, each pair one');
	const { store, sent } = consoleWith(rows, 100);
	const byId = new Map(rows.map((r) => [r.objectId, r]));
	const asked: string[][] = [];
	assert.equal(requestRemoval(ids, { onRemoveDocument: () => assert.fail('never the single dialog for a queue'), onRemoveDocuments: (objectIds) => asked.push([...objectIds]) }), true);
	assert.deepEqual(asked, [ids], 'the whole queue, never cut to write_ids_max');
	store.requestRemove(asked[0]!.map((objectId) => ({ objectId, path: byId.get(objectId)!.path, chunks: byId.get(objectId)!.chunks })));
	const pending = store.getState().confirm;
	assert.equal(pending?.kind, 'multi');
	assert.deepEqual(
		pending?.targets.map((t) => t.objectId),
		ids
	);
	const dialog = multiRemoveConfirmation(pending!.targets, PG);
	assert.equal(dialog.title, 'Remove 5 documents?');
	assert.deepEqual(dialog.typed, { expected: '5', prompt: 'Type 5 to confirm.' });
	assert.deepEqual(
		dialog.listed,
		ids.map((id) => byId.get(id)!.path)
	);
	assert.deepEqual(sent, [], 'nothing is sent while the dialog is open');
	store.cancelRemove();
	assert.deepEqual(sent, [], 'Cancel sends nothing');
	store.dispose();
});

test("confirming the queue sends it in batches of the node's write_ids_max, every queued document once", async () => {
	const { ids, rows } = demoQueue();
	const { store, sent } = consoleWith(rows, 2);
	store.requestRemove(ids.map((objectId) => ({ objectId, path: objectId, chunks: null })));
	await store.confirmRemove();
	assert.deepEqual(
		sent.map((b) => b.length),
		[2, 2, 1]
	);
	assert.deepEqual(sent.flat(), ids);
	assert.equal(store.getState().removal.status, 'done');
	store.dispose();
});
