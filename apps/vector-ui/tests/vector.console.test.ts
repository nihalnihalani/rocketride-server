// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CONSOLE CONTROLLER: full and quick stats, background paging, chunks, and the confirmed removal
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ExplorerToolError } from 'shared/explorer';
import { manualClock } from 'shared/explorer/connect/testing';
import type { IDocumentItem } from '../src/contract/types';
import { QUICK_STATS_INTERVAL_MS } from '../src/vector/budgets';
import { createConsoleStore } from '../src/vector/consoleStore';
import type { IConsoleDeps } from '../src/vector/consoleStore';
import { readChunksPage, readDocumentsPage, readRemoveResult, readStats } from '../src/vector/results';
import type { IDocumentsPageView } from '../src/vector/results';
import { CANCELLED_TEXT, CODE_SENTENCES } from '../src/vector/wording';
import { fixture } from './support/fixtures';

interface ICall {
	tool: string;
	args: unknown[];
}

/** A doc row. */
function doc(objectId: string, path: string): IDocumentItem {
	return { objectId, path, chunks: 2, has_first_chunk: true, tables: 0, deleted: false, nodeId: null, size: null, modifyTime: null, ingestedAt: null, pointId: null };
}

/** A controller over scripted tools and a manual clock. */
function harness(over: Partial<IConsoleDeps> = {}) {
	const clock = manualClock(Date.parse('2026-10-08T18:31:00Z'));
	const calls: ICall[] = [];
	const announced: string[] = [];
	const removedIds: string[][] = [];
	const deps: IConsoleDeps = {
		stats: async (mode) => {
			calls.push({ tool: 'stats', args: [mode] });
			return readStats(mode === 'quick' ? fixture('stats_quick') : fixture('stats_pgvector'));
		},
		documents: async (cursor, limit) => {
			calls.push({ tool: 'documents', args: [cursor, limit] });
			return readDocumentsPage(cursor ? fixture('documents_page2_last') : fixture('documents_page1'));
		},
		chunks: async (objectId, after, limit) => {
			calls.push({ tool: 'chunks', args: [objectId, after, limit] });
			return readChunksPage(fixture('chunks_page'));
		},
		remove: async (ids) => {
			calls.push({ tool: 'remove_document', args: [ids] });
			return readRemoveResult({ ...fixture('remove_document_ok'), removed: ids.map((objectId) => ({ objectId, chunks_removed: 12 })), removed_chunks: 12 * ids.length });
		},
		announce: (text) => announced.push(text),
		onRemoved: (ids) => removedIds.push([...ids]),
		clock,
		...over,
	};
	const store = createConsoleStore(deps, { pageSize: 500, chunkPage: 100, writeBatch: 100 });
	return { store, clock, calls, announced, removedIds, tools: () => calls.map((c) => c.tool) };
}

test('opening the console: a full stats call and the directory loading every page in the background', async () => {
	const { store, clock, calls } = harness();
	store.open();
	await clock.settle();
	assert.deepEqual(
		calls.map((c) => [c.tool, ...c.args]),
		[
			['stats', 'full'],
			['documents', null, 500],
			['documents', readDocumentsPage(fixture('documents_page1')).nextCursor, 500],
		]
	);
	const state = store.getState();
	assert.equal(state.stats.view?.documents, 42);
	assert.equal(state.stats.mode, 'full');
	assert.equal(state.directory.status, 'done');
	assert.equal(state.directory.rows.length, 7);
	store.dispose();
});

test('quick stats every 15 s while visible, none while hidden, and Refresh is a full call', async () => {
	const { store, clock, tools } = harness();
	store.open();
	await clock.settle();
	await clock.advance(QUICK_STATS_INTERVAL_MS - 1);
	assert.equal(tools().filter((t) => t === 'stats').length, 1, 'not before 15 s');
	await clock.advance(1);
	assert.equal(tools().filter((t) => t === 'stats').length, 2);
	assert.equal(store.getState().stats.mode, 'quick');
	assert.equal(store.getState().stats.view?.countsAsOf, '2026-10-08T18:30:40Z');
	store.setVisible(false);
	await clock.advance(QUICK_STATS_INTERVAL_MS * 4);
	assert.equal(tools().filter((t) => t === 'stats').length, 2, 'no call while the console is hidden');
	store.setVisible(true);
	await clock.advance(QUICK_STATS_INTERVAL_MS);
	assert.equal(tools().filter((t) => t === 'stats').length, 3);
	store.refresh();
	await clock.settle();
	assert.equal(store.getState().stats.mode, 'full');
	store.dispose();
	const before = tools().length;
	await clock.advance(QUICK_STATS_INTERVAL_MS * 3);
	assert.equal(tools().length, before, 'nothing after dispose');
});

test('a stats failure keeps the last figures and says why', async () => {
	let fail = false;
	const { store, clock } = harness({
		stats: async () => {
			if (fail) throw new ExplorerToolError({ kind: 'store', tool: 'stats', message: 'OperationalError: the store did not answer', code: 'STORE_ERROR' });
			return readStats(fixture('stats_pgvector'));
		},
	});
	store.open();
	await clock.settle();
	fail = true;
	store.refresh();
	await clock.settle();
	const { stats } = store.getState();
	assert.equal(stats.status, 'error');
	assert.equal(stats.view?.documents, 42, 'the strip keeps its last values (shown greyed)');
	assert.deepEqual(stats.error, { headline: CODE_SENTENCES.STORE_ERROR, detail: 'OperationalError: the store did not answer' });
	store.dispose();
});

test('hiding the console pauses the directory (rows sorted), showing it resumes at the cursor', async () => {
	const pages: IDocumentsPageView[] = [
		{ items: [doc('m', 'C:/b/m.md')], nextCursor: 'c1', total: 3, countsExact: true, distinct: true, sorted: true, caveats: [], warnings: [], pagingUnsupported: false },
		{ items: [doc('a', 'C:/a/a.md')], nextCursor: 'c2', total: 3, countsExact: true, distinct: true, sorted: true, caveats: [], warnings: [], pagingUnsupported: false },
		{ items: [doc('z', 'C:/c/z.md')], nextCursor: null, total: 3, countsExact: true, distinct: true, sorted: true, caveats: [], warnings: [], pagingUnsupported: false },
	];
	let release: (() => void) | null = null;
	const { store, clock, calls } = harness({
		documents: async (cursor, limit) => {
			calls.push({ tool: 'documents', args: [cursor, limit] });
			const index = cursor === null ? 0 : cursor === 'c1' ? 1 : 2;
			if (index === 1) await new Promise<void>((resolve) => (release = resolve));
			return pages[index];
		},
	});
	store.open();
	await clock.settle();
	store.setVisible(false);
	release!();
	await clock.settle();
	assert.equal(store.getState().directory.status, 'paused');
	assert.deepEqual(
		store.getState().directory.rows.map((r) => r.objectId),
		['a', 'm'],
		'paused: what is loaded is sorted'
	);
	assert.equal(calls.filter((c) => c.tool === 'documents').length, 2, 'no page is asked for while hidden');
	store.setVisible(true);
	await clock.settle();
	assert.equal(store.getState().directory.status, 'done');
	assert.deepEqual(
		calls.filter((c) => c.tool === 'documents').map((c) => c.args[0]),
		[null, 'c1', 'c2']
	);
	store.dispose();
});

test('a refresh while pages arrive starts over, and a late page of the old listing is dropped', async () => {
	let release: (() => void) | null = null;
	let first = true;
	const { store, clock } = harness({
		documents: async (cursor) => {
			if (cursor !== null && first) {
				first = false;
				await new Promise<void>((resolve) => (release = resolve));
				return { ...readDocumentsPage(fixture('documents_page2_last')), items: [doc('late', 'late.md')] };
			}
			return readDocumentsPage(cursor ? fixture('documents_page2_last') : fixture('documents_page1'));
		},
	});
	store.open();
	await clock.settle();
	store.refresh();
	await clock.settle();
	release!();
	await clock.settle();
	assert.ok(!store.getState().directory.rows.some((r) => r.objectId === 'late'), "the old listing's page never lands");
	assert.equal(store.getState().directory.status, 'done');
	store.dispose();
});

test('a failed page stops the listing with the reason; Retry asks for the same cursor', async () => {
	let fail = true;
	const { store, clock, calls } = harness({
		documents: async (cursor, limit) => {
			calls.push({ tool: 'documents', args: [cursor, limit] });
			if (cursor !== null && fail) throw new ExplorerToolError({ kind: 'timeout', tool: 'documents', message: 'Stopped waiting for documents after 40 s.' });
			return readDocumentsPage(cursor ? fixture('documents_page2_last') : fixture('documents_page1'));
		},
	});
	store.open();
	await clock.settle();
	assert.equal(store.getState().directory.status, 'error');
	assert.equal(store.getState().directory.rows.length, 5);
	fail = false;
	store.retryDocuments();
	await clock.settle();
	assert.equal(store.getState().directory.status, 'done');
	const cursors = calls.filter((c) => c.tool === 'documents').map((c) => c.args[0]);
	assert.equal(cursors[1], cursors[2], 'the same cursor again');
	store.dispose();
});

test('selecting a document lists its chunks, 100 per page, and "more" continues after the last one', async () => {
	const { store, clock, calls } = harness();
	store.open();
	await clock.settle();
	store.selectDocument('kestrel');
	await clock.settle();
	assert.deepEqual(
		store.getState().chunks.items.map((c) => c.chunkId),
		[0, 1, 2]
	);
	assert.equal(store.getState().chunks.hasMore, true);
	store.loadMoreChunks();
	await clock.settle();
	assert.deepEqual(
		calls.filter((c) => c.tool === 'chunks').map((c) => c.args),
		[
			['kestrel', -1, 100],
			['kestrel', 2, 100],
		]
	);
	store.selectDocument(null);
	assert.equal(store.getState().chunks.objectId, null);
	store.dispose();
});

test('remove: asking opens the confirmation and sends nothing; Cancel sends nothing and says so', async () => {
	const { store, clock, tools, announced } = harness();
	store.setWritesEnabled(true);
	store.open();
	await clock.settle();
	store.requestRemove([{ objectId: 'kestrel', path: 'C:/demo/field/kestrel_field_guide.md', chunks: 12 }]);
	assert.equal(store.getState().confirm?.targets.length, 1);
	assert.ok(!tools().includes('remove_document'), 'nothing is sent before Confirm');
	store.cancelRemove();
	await clock.settle();
	assert.equal(store.getState().confirm, null);
	assert.ok(!tools().includes('remove_document'), 'Cancel sends nothing');
	assert.deepEqual(announced, [CANCELLED_TEXT]);
	assert.equal(store.getState().removal.message, CANCELLED_TEXT);
	store.dispose();
});

test('remove: Confirm sends the batch once, announces the rows removed, refreshes stats in full and the directory, and forgets the document', async () => {
	const { store, clock, calls, announced, removedIds } = harness();
	store.setWritesEnabled(true);
	store.open();
	await clock.settle();
	store.selectDocument('kestrel');
	await clock.settle();
	calls.length = 0;
	store.requestRemove([{ objectId: 'kestrel', path: 'C:/demo/field/kestrel_field_guide.md', chunks: 12 }]);
	await store.confirmRemove();
	await clock.settle();
	assert.deepEqual(calls.map((c) => [c.tool, ...c.args]).slice(0, 2), [
		['remove_document', ['kestrel']],
		['stats', 'full'],
	]);
	assert.ok(
		calls.some((c) => c.tool === 'documents' && c.args[0] === null),
		'the directory starts over'
	);
	assert.deepEqual(announced, ['Removed C:/demo/field/kestrel_field_guide.md (12 chunks)']);
	assert.deepEqual(removedIds, [['kestrel']]);
	assert.equal(store.getState().chunks.objectId, null, "the removed document's chunk list closes");
	assert.equal(store.getState().confirm, null);
	store.dispose();
});

test('remove: refused by the node, the sentence names the rule; with writes off nothing is ever sent', async () => {
	let sent = 0;
	const { store, clock, announced } = harness({
		remove: async () => {
			sent += 1;
			throw new ExplorerToolError({ kind: 'store', tool: 'remove_document', message: 'Only a Tools source may remove documents.', code: 'WRITES_SOURCE' });
		},
	});
	store.setWritesEnabled(true);
	store.open();
	await clock.settle();
	store.requestRemove([{ objectId: 'k', path: 'k.md', chunks: 1 }]);
	await store.confirmRemove();
	assert.deepEqual(announced, [CODE_SENTENCES.WRITES_SOURCE]);
	assert.equal(store.getState().removal.status, 'error');
	store.setWritesEnabled(false);
	store.requestRemove([{ objectId: 'k', path: 'k.md', chunks: 1 }]);
	assert.equal(store.getState().confirm, null, 'no confirmation opens while writes are off');
	await store.confirmRemove();
	assert.equal(sent, 1, 'only the first, refused, call');
	store.dispose();
});

test('several documents go in batches of write_ids_max and stop at the first error', async () => {
	const sent: string[][] = [];
	const { store, clock, announced } = harness({
		remove: async (ids) => {
			sent.push([...ids]);
			if (sent.length === 2) throw new ExplorerToolError({ kind: 'store', tool: 'remove_document', message: 'x', code: 'WRITES_DISABLED' });
			return readRemoveResult({ success: true, removed: ids.map((objectId) => ({ objectId, chunks_removed: 1 })), not_found: [], removed_chunks: ids.length });
		},
	});
	store.setWritesEnabled(true);
	const targets = Array.from({ length: 250 }, (_, i) => ({ objectId: `id-${i}`, path: `f${i}.md`, chunks: 1 }));
	store.requestRemove(targets);
	assert.equal(store.getState().confirm?.kind, 'multi');
	await store.confirmRemove();
	await clock.settle();
	assert.deepEqual(
		sent.map((b) => b.length),
		[100, 100]
	);
	assert.equal(announced[0], `Removed 100 documents (100 chunks). Stopped after 1 of 3 batches: ${CODE_SENTENCES.WRITES_DISABLED}`);
	store.dispose();
});
