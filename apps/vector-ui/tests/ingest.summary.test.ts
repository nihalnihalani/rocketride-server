// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// INGEST SUMMARY: what a drop became
// =============================================================================
//
// The upload queue keeps every drop (its rows, each row as it ended, its
// start and end), so one line can say "Drop of 12 files: 9 added (341
// chunks) · 2 replaced (19 chunks) · 1 not added · 00:48", live while the
// drop runs and still after Clear finished drops its rows. The upload list
// still holds the summary's placeholder above its rows.
// =============================================================================

import assert from 'node:assert/strict';
import Module from 'node:module';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test as nodeTest } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ISendFile } from 'shared/explorer';
import type { IUploadEvent } from '../src/contract/types';
import type { CallOutcome } from '../src/chat/toolCalls';
import type { DropCandidate, IngestDrop, UploadRow } from '../src/vector/uploads';
import type { IngestDeps } from '../src/ingest/ingestQueue';

/** Most a test here may take: they await fakes, so a regression must fail, not hang the run. */
const TEST_TIMEOUT_MS = 10_000;

/**
 * Declare a test bounded by {@link TEST_TIMEOUT_MS}.
 *
 * @param name - What it checks.
 * @param fn - The test.
 */
function test(name: string, fn: () => void | Promise<void>): void {
	void nodeTest(name, { timeout: TEST_TIMEOUT_MS }, fn);
}

// ── Shell stand-ins (installed before any panel module loads) ────────────────

const h = React.createElement;
const shellStandIn = {
	commonStyles: new Proxy({}, { get: () => ({}) }),
	EmptyState: ({ title, description }: { title: string; description?: string }) => h('div', { 'data-empty-state': '' }, h('strong', null, title), description ? h('p', null, description) : null),
	ConfirmDialog: (props: { title: string; message: React.ReactNode }) => h('div', { role: 'dialog', 'aria-label': props.title }, props.message),
	useShellEvent: () => undefined,
};
const moduleWithLoad = Module as unknown as { _load: (request: string, parent: unknown, isMain: boolean) => unknown };
const originalLoad = moduleWithLoad._load;
moduleWithLoad._load = function (request: string, parent: unknown, isMain: boolean): unknown {
	if (request === 'shell') return shellStandIn;
	return originalLoad.call(this, request, parent, isMain);
};

const uploads = require('../src/vector/uploads') as typeof import('../src/vector/uploads');
const { NO_MAP_SENTENCE, NO_PLACING_SENTENCE, SHOW_NEW_LABEL, UNCOUNTED_SENTENCE, dropSummaryText, formatElapsed, newChunkKeys, placedSentence, settleDrops, showNewChunksReason, summariseDrop, uploadLabel } = uploads;
const { createIngestQueue } = require('../src/ingest/ingestQueue') as typeof import('../src/ingest/ingestQueue');
const { createNameLocks } = require('../src/ingest/nameLocks') as typeof import('../src/ingest/nameLocks');
const { objectIdForPath } = require('../src/vector/objectId') as typeof import('../src/vector/objectId');
const { UploadList } = require('../src/components/UploadList') as typeof import('../src/components/UploadList');

// ── Fixtures and fakes ──────────────────────────────────────────────────────

/**
 * Read a provisional fixture.
 *
 * @param name - File name.
 * @returns The parsed JSON.
 */
function fixture<T>(name: string): T {
	return JSON.parse(readFileSync(path.join(__dirname, 'fixtures', 'provisional', name), 'utf8')) as T;
}

/**
 * An upload row.
 *
 * @param id - Row id.
 * @param rowPath - Stored path.
 * @param status - Where it is.
 * @param extra - Fields to replace.
 * @returns The row.
 */
function row(id: string, rowPath: string, status: UploadRow['status'], extra: Partial<UploadRow> = {}): UploadRow {
	return { id, path: rowPath, name: rowPath.slice(rowPath.lastIndexOf('/') + 1), objectId: `oid-${id}`, size: 100, status, bytesSent: 0, fileSize: 100, chunks: null, existingChunks: null, message: null, detail: null, ...extra };
}

/**
 * A drop over the given rows, all of them ended (as the queue records them).
 *
 * @param rows - Its rows.
 * @param startedAt - When it was dropped.
 * @param finishedAt - When its last file ended, or null.
 * @returns The drop.
 */
function dropOf(rows: readonly UploadRow[], startedAt: number, finishedAt: number | null): IngestDrop {
	const ended: Record<string, UploadRow> = {};
	for (const one of rows) if (uploads.FINISHED.has(one.status)) ended[one.id] = one;
	return { id: 'd1', startedAt, finishedAt, rowIds: rows.map((one) => one.id), ended, shown: null };
}

/**
 * A drop candidate.
 *
 * @param relPath - Path in the drop.
 * @param size - Bytes.
 * @returns The candidate.
 */
function candidate(relPath: string, size = 100): DropCandidate {
	return { file: { name: relPath.slice(relPath.lastIndexOf('/') + 1), size, type: '' } as unknown as File, relPath };
}

/** A promise and its resolver. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
	let resolve: (value: T) => void = () => undefined;
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

/** A clock the tests move by hand. */
interface Clock {
	at: number;
	now(): number;
}

/**
 * A manual clock.
 *
 * @param at - The start.
 * @returns The clock.
 */
function manualClock(at = 1_700_000_000_000): Clock {
	const clock: Clock = { at, now: () => clock.at };
	return clock;
}

/**
 * Fake queue dependencies: paths in `stored` are already stored, every upload
 * completes (unless its path is in `fail`), the store then counts `counts[path]`
 * (default 2) chunks, and each send moves the clock by `sendMs`.
 *
 * @param options - Stored paths, counts, failures, the clock and the send time.
 * @returns The deps and what they saw.
 */
function fakeDeps(options: { stored?: Record<string, number>; counts?: Record<string, number | null>; fail?: ReadonlySet<string>; clock?: Clock; sendMs?: number; events?: (files: ISendFile[]) => Promise<void>; canProbe?: boolean; sendResult?: (file: ISendFile) => Record<string, unknown> } = {}): { deps: IngestDeps; announced: string[] } {
	const announced: string[] = [];
	const pathOf = new Map<string, string>();
	const deps: IngestDeps = {
		canProbe: options.canProbe ?? true,
		canCount: true,
		async callTool(tool, input): Promise<CallOutcome> {
			if (tool === 'chunks') {
				const stored = Object.entries(options.stored ?? {}).find(([storedPath]) => objectIdForPath(storedPath) === input.object_id);
				if (stored === undefined) return { ok: false, code: 'NOT_FOUND', message: 'not stored', kind: null, error: null };
				return { ok: true, value: { success: true, items: [{ chunkId: 0 }], total: stored[1] } };
			}
			const id = (input.object_ids as string[])[0];
			const stored = pathOf.get(id) ?? '';
			const count = options.counts && stored in options.counts ? options.counts[stored] : 2;
			return { ok: true, value: { success: true, items: [{ objectId: id, chunks: count }] } };
		},
		async sendFiles(files) {
			if (options.events) await options.events(files);
			if (options.clock) options.clock.at += options.sendMs ?? 0;
			return files.map((file) => {
				const name = String(file.objinfo?.name);
				if (options.sendResult) {
					const result = options.sendResult(file);
					const reported = (result.result as Record<string, unknown> | undefined)?.objectId;
					pathOf.set(typeof reported === 'string' ? reported : objectIdForPath(name), name);
					return result;
				}
				pathOf.set(objectIdForPath(name), name);
				const failed = options.fail?.has(name) ?? false;
				return { action: failed ? 'error' : 'complete', filepath: file.file.name, bytes_sent: file.file.size, file_size: file.file.size, upload_time: 0.1, ...(failed ? { error: 'Pipe closed with an error' } : {}) };
			});
		},
		onDocumentsChanged: () => undefined,
		announce(message) {
			announced.push(message);
		},
		sleep: async () => undefined,
		locks: createNameLocks(),
		...(options.clock ? { now: options.clock.now } : {}),
	};
	return { deps, announced };
}

/**
 * Render to static markup.
 *
 * @param element - The element.
 * @returns The markup.
 */
function render(element: React.ReactElement): string {
	return renderToStaticMarkup(element);
}

// ── The sentence ────────────────────────────────────────────────────────────

test('summary: a finished drop of 12 files reads added, replaced and not added, with chunks and the time it took', () => {
	const added = [40, 40, 40, 40, 40, 40, 40, 40, 21].map((chunks, i) => row(`a${i}`, `docs/a${i}.md`, 'done', { chunks }));
	const replaced = [12, 7].map((chunks, i) => row(`r${i}`, `docs/r${i}.pdf`, 'done', { chunks, replaces: true }));
	const refused = row('x0', 'docs/x.exe', 'refused', { message: 'Not added: .exe files are not supported.' });
	const rows = [...added, ...replaced, refused];
	const summary = summariseDrop(dropOf(rows, 1_000_000, 1_048_300), [], 9_999_999);
	assert.equal(dropSummaryText(summary), 'Drop of 12 files: 9 added (341 chunks) · 2 replaced (19 chunks) · 1 not added · 00:48');
	assert.equal(summary.files, 12);
	assert.equal(summary.added, 9);
	assert.equal(summary.replaced, 2);
	assert.equal(summary.notAdded, 1);
	assert.equal(summary.finished, true);
	assert.equal(summary.newChunks, 360);
	assert.deepEqual(
		summary.newDocuments.map((doc) => [doc.objectId, doc.chunks]),
		[...added, ...replaced].map((one) => [one.objectId, one.chunks])
	);
});

test('summary: live while the drop runs — waiting, in progress, cancelled and failed rows, and the clock from the drop', () => {
	const rows = [
		row('u1', 'a.md', 'done', { chunks: 7 }),
		row('u2', 'b.md', 'uploading', { bytesSent: 40 }),
		row('u3', 'c.md', 'confirm'),
		row('u4', 'd.md', 'queued'),
		row('u5', 'e.md', 'cancelled', { message: 'Cancelled. Nothing was sent.' }),
		row('u6', 'f.md', 'failed', { message: 'Failed.' }),
	];
	const drop = dropOf(rows, 5_000, null);
	const summary = summariseDrop(drop, rows, 10_400);
	assert.equal(summary.finished, false);
	assert.equal(dropSummaryText(summary), 'Drop of 6 files: 1 added (7 chunks) · 1 not added · 1 cancelled · 1 waiting for your answer · 2 in progress · 00:05');
	// The rows in flight come from the live list, the ended ones from the drop's record.
	const later = rows.map((one) => (one.id === 'u2' ? { ...one, status: 'processing' as const } : one));
	assert.equal(summariseDrop(drop, later, 70_000).inProgress, 2);
	assert.equal(dropSummaryText(summariseDrop(drop, later, 70_000)).endsWith('· 01:05'), true);
});

test('summary: singulars, zero chunks, and counts the store did not report are never presented as counted', () => {
	assert.equal(dropSummaryText(summariseDrop(dropOf([row('u1', 'a.md', 'done', { chunks: 1 })], 0, 2_000), [], 0)), 'Drop of 1 file: 1 added (1 chunk) · 00:02');
	assert.equal(dropSummaryText(summariseDrop(dropOf([row('u1', 'a.pdf', 'done', { chunks: 0 })], 0, 1_000), [], 0)), 'Drop of 1 file: 1 added (0 chunks) · 00:01');
	const some = [row('u1', 'a.md', 'done', { chunks: 5 }), row('u2', 'b.md', 'done'), row('u3', 'c.md', 'done')];
	const partly = summariseDrop(dropOf(some, 0, 3_000), [], 0);
	assert.equal(dropSummaryText(partly), 'Drop of 3 files: 3 added (5 chunks; 2 not counted) · 00:03');
	assert.equal(partly.uncounted, 2);
	assert.equal(partly.newChunks, 5);
	assert.deepEqual(
		partly.newDocuments.map((doc) => doc.objectId),
		['oid-u1']
	);
	const none = summariseDrop(dropOf([row('u1', 'a.md', 'done'), row('u2', 'b.md', 'done', { replaces: true })], 0, 0), [], 0);
	assert.equal(dropSummaryText(none), 'Drop of 2 files: 1 added (chunks not counted) · 1 replaced (chunks not counted) · 00:00');
	assert.equal(none.newChunks, 0);
});

test('formatElapsed: minutes and seconds, hours when it takes that long, never negative', () => {
	assert.equal(formatElapsed(0), '00:00');
	assert.equal(formatElapsed(48_900), '00:48');
	assert.equal(formatElapsed(754_000), '12:34');
	assert.equal(formatElapsed(3_723_000), '1:02:03');
	assert.equal(formatElapsed(-5), '00:00');
	assert.equal(formatElapsed(Number.NaN), '00:00');
});

// ── Where the new chunks go ─────────────────────────────────────────────────

test('newChunkKeys: every new document gets its first chunk before any gets a second; the cap cuts the list, the total does not', () => {
	const docs = [
		{ objectId: 'A', path: 'a.md', chunks: 3 },
		{ objectId: 'B', path: 'b.md', chunks: 1 },
		{ objectId: 'C', path: 'c.md', chunks: 2 },
	];
	assert.deepEqual(newChunkKeys(docs, 4), {
		keys: [
			['A', 0],
			['B', 0],
			['C', 0],
			['A', 1],
		],
		total: 6,
	});
	assert.deepEqual(newChunkKeys(docs, 200).keys, [
		['A', 0],
		['B', 0],
		['C', 0],
		['A', 1],
		['C', 1],
		['A', 2],
	]);
	const many = [40, 40, 40, 40, 40, 40, 40, 40, 21].map((chunks, i) => ({ objectId: `d${i}`, path: `d${i}.md`, chunks }));
	const capped = newChunkKeys(many, 200);
	assert.equal(capped.total, 341);
	assert.equal(capped.keys.length, 200);
	assert.equal(new Set(capped.keys.map((key) => `${key[0]}#${key[1]}`)).size, 200, 'no key twice');
	assert.deepEqual(new Set(capped.keys.map((key) => key[0])), new Set(many.map((doc) => doc.objectId)), 'every document is placed');
	assert.deepEqual(newChunkKeys([], 200), { keys: [], total: 0 });
	assert.deepEqual(newChunkKeys(docs, 0).keys, []);
});

test('placedSentence and the reasons the map cannot show new chunks', () => {
	assert.equal(placedSentence(200, 341, 200), '200 of 341 new chunks placed: the map pins at most 200 chunks outside its sample.');
	assert.equal(placedSentence(6, 6, 200), null);
	assert.equal(showNewChunksReason({}), null);
	assert.equal(showNewChunksReason({ sample: true, project: true }), null);
	assert.equal(showNewChunksReason({ sample: false }), NO_MAP_SENTENCE);
	assert.equal(showNewChunksReason({ sample: true, project: false }), NO_PLACING_SENTENCE);
	assert.match(NO_MAP_SENTENCE, /cannot draw a map/);
	assert.match(NO_PLACING_SENTENCE, /Draw a new sample on the Map tab/);
	assert.equal(SHOW_NEW_LABEL, 'Show new chunks on the map');
});

test('settleDrops: a row is recorded as it ends, and the drop ends with its last row', () => {
	const rows = [row('u1', 'a.md', 'done', { chunks: 2 }), row('u2', 'b.md', 'uploading')];
	const drop: IngestDrop = { id: 'd1', startedAt: 0, finishedAt: null, rowIds: ['u1', 'u2'], ended: {}, shown: null };
	const first = settleDrops([drop], rows, 1_000);
	assert.deepEqual(Object.keys(first.drops[0].ended), ['u1']);
	assert.equal(first.drops[0].finishedAt, null);
	assert.deepEqual(first.finished, []);
	assert.equal(settleDrops(first.drops, rows, 1_500).drops[0], first.drops[0], 'nothing changed: the same drop');
	const done = rows.map((one) => (one.id === 'u2' ? { ...one, status: 'done' as const, chunks: 3 } : one));
	const second = settleDrops(first.drops, done, 4_000);
	assert.equal(second.drops[0].finishedAt, 4_000);
	assert.deepEqual(
		second.finished.map((one) => one.id),
		['d1']
	);
	assert.equal(settleDrops(second.drops, [], 9_000).drops[0], second.drops[0], 'a finished drop never changes');
});

// ── The queue keeps a summary per drop ──────────────────────────────────────

test('queue: a 3-file drop reports "3 added (6 chunks)" with its time, and says it once the drop is done', async () => {
	const clock = manualClock();
	const fake = fakeDeps({ clock, sendMs: 4_000 });
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('a.md'), candidate('b.md'), candidate('c.md')]);
	await queue.idle();
	const state = queue.getState();
	assert.equal(state.drops.length, 1);
	const summary = summariseDrop(state.drops[0], state.rows, clock.at + 60_000);
	assert.equal(dropSummaryText(summary), 'Drop of 3 files: 3 added (6 chunks) · 00:04');
	assert.equal(state.drops[0].finishedAt, clock.at);
	assert.deepEqual(state.drops[0].rowIds, state.rows.map((one) => one.id));
	// The drop's line is said after its last file's own line, once.
	const said = fake.announced.filter((message) => message.startsWith('Drop of'));
	assert.deepEqual(said, ['Drop of 3 files: 3 added (6 chunks) · 00:04']);
	assert.ok(fake.announced.indexOf(said[0]) > fake.announced.indexOf('c.md: 2 chunks added'));
});

test('queue: a one-file drop is summarised but not announced twice (its row already said it)', async () => {
	const fake = fakeDeps({ clock: manualClock(), sendMs: 1_000 });
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('only.md')]);
	await queue.idle();
	assert.equal(queue.getState().drops.length, 1);
	assert.ok(fake.announced.includes('only.md: 2 chunks added'));
	assert.ok(!fake.announced.some((message) => message.startsWith('Drop of')));
});

test('queue: duplicate base names — the summary matches the upload events and results, file by file', async () => {
	const script = fixture<{ files: Array<{ relPath: string; size: number }>; events: IUploadEvent[] }>('upload_events_duplicate_basename.json');
	const eventsOf = new Map<number, IUploadEvent[]>();
	for (const event of script.events) eventsOf.set(event.file_size, [...(eventsOf.get(event.file_size) ?? []), event]);
	let queueRef: ReturnType<typeof createIngestQueue> | null = null;
	const live: Array<{ size: number; line: string }> = [];
	const clock = manualClock();
	const fake = fakeDeps({
		clock,
		sendMs: 2_000,
		fail: new Set(['notes/memo.md']),
		counts: { 'a/report.pdf': 5, 'b/report.pdf': 4 },
		async events(files) {
			const queue = queueRef as ReturnType<typeof createIngestQueue>;
			for (const event of eventsOf.get(files[0].file.size) ?? []) {
				queue.handleEvent(event);
				const state = queue.getState();
				live.push({ size: event.file_size, line: dropSummaryText(summariseDrop(state.drops[0], state.rows, clock.at)) });
			}
		},
	});
	const queue = createIngestQueue(fake.deps);
	queueRef = queue;
	await queue.addDrop([...script.files.map((file) => candidate(file.relPath, file.size)), candidate('notes/memo.md', 10)]);
	await queue.idle();
	const state = queue.getState();
	assert.deepEqual(
		state.rows.map((one) => [one.path, one.status]),
		[
			['a/report.pdf', 'done'],
			['b/report.pdf', 'done'],
			['notes/memo.md', 'failed'],
		]
	);
	const summary = summariseDrop(state.drops[0], state.rows, clock.at);
	assert.equal(dropSummaryText(summary), 'Drop of 3 files: 2 added (9 chunks) · 1 not added · 00:06');
	assert.equal(summary.added, state.rows.filter((one) => one.status === 'done').length);
	assert.equal(summary.notAdded, state.rows.filter((one) => one.status === 'failed').length);
	assert.deepEqual(
		summary.newDocuments.map((doc) => [doc.path, doc.objectId, doc.chunks]),
		[
			['a/report.pdf', objectIdForPath('a/report.pdf'), 5],
			['b/report.pdf', objectIdForPath('b/report.pdf'), 4],
		]
	);
	// memo.md (a unique name) went first and failed; while the two report.pdf files were sent one after the
	// other, the line counted the one in flight as in progress, never as added before its result.
	assert.equal(live.length, script.events.length);
	for (const { size, line } of live) {
		if (size === 120000) assert.match(line, /^Drop of 3 files: 1 not added · 2 in progress · 00:02$/);
		else assert.match(line, /^Drop of 3 files: (1 added \(5 chunks\) · 1 not added · 1 in progress|1 not added · 2 in progress) · 00:04$/);
	}
});

test('queue: Replace counts as replaced and Cancel as cancelled; refused files are not added', async () => {
	const fake = fakeDeps({ stored: { 'report.pdf': 19, 'old.md': 4 }, counts: { 'report.pdf': 3, 'new.md': 6 } });
	const queue = createIngestQueue(fake.deps);
	const first = queue.addDrop([candidate('report.pdf'), candidate('new.md'), candidate('virus.exe')]);
	await queue.waitFor((state) => state.confirm !== null);
	queue.answerConfirm(true);
	await first;
	await queue.idle();
	const second = queue.addDrop([candidate('old.md'), candidate('fresh.md')]);
	await queue.waitFor((state) => state.confirm !== null);
	queue.answerConfirm(false);
	await second;
	await queue.idle();
	const state = queue.getState();
	assert.equal(state.drops.length, 2);
	assert.match(dropSummaryText(summariseDrop(state.drops[0], state.rows, 0)), /^Drop of 3 files: 1 added \(6 chunks\) · 1 replaced \(3 chunks\) · 1 not added · /);
	assert.match(dropSummaryText(summariseDrop(state.drops[1], state.rows, 0)), /^Drop of 2 files: 1 added \(2 chunks\) · 1 cancelled · /);
	const replaced = state.rows.find((one) => one.path === 'report.pdf') as UploadRow;
	assert.equal(replaced.replaces, true);
	assert.equal(uploadLabel(replaced), 'Replaced: 3 chunks stored');
	assert.equal(state.rows.find((one) => one.path === 'new.md')?.replaces ?? false, false);
	assert.equal(state.rows.find((one) => one.path === 'old.md')?.replaces ?? false, false, 'a cancelled replacement replaced nothing');
});

test('queue: a file the store could not check, sent anyway, counts as added (the store did not say it replaced anything)', async () => {
	const fake = fakeDeps({ canProbe: false });
	const queue = createIngestQueue(fake.deps);
	const drop = queue.addDrop([candidate('x.md'), candidate('y.md')]);
	await queue.waitFor((state) => state.confirm !== null);
	queue.answerConfirm(true);
	await drop;
	await queue.idle();
	const state = queue.getState();
	assert.match(dropSummaryText(summariseDrop(state.drops[0], state.rows, 0)), /^Drop of 2 files: 2 added \(4 chunks\) · /);
	assert.equal(uploadLabel(state.rows[0]), '2 chunks added');
});

test('queue: Clear finished removes finished drops and keeps a running drop whole, counting the rows it cleared', async () => {
	const gate = deferred<void>();
	let gated = false;
	const fake = fakeDeps();
	const sendFiles = fake.deps.sendFiles;
	fake.deps.sendFiles = async (files, options) => {
		if (gated) await gate.promise;
		return sendFiles(files, options);
	};
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('first.md')]);
	await queue.idle();
	gated = true;
	await queue.addDrop([candidate('bad.exe'), candidate('slow.md')]);
	await queue.waitFor((state) => state.rows.some((one) => one.path === 'slow.md' && one.status === 'queued'));
	queue.clearFinished();
	let state = queue.getState();
	assert.deepEqual(
		state.rows.map((one) => one.path),
		['slow.md']
	);
	assert.equal(state.drops.length, 1, 'the finished drop went with its rows');
	assert.match(dropSummaryText(summariseDrop(state.drops[0], state.rows, Date.now())), /^Drop of 2 files: 1 not added · 1 in progress · /);
	gate.resolve();
	await queue.idle();
	state = queue.getState();
	assert.match(dropSummaryText(summariseDrop(state.drops[0], state.rows, Date.now())), /^Drop of 2 files: 1 added \(2 chunks\) · 1 not added · /);
	queue.clearFinished();
	assert.deepEqual(queue.getState().drops, []);
});

test('queue: dispose forgets every drop; a drop with nothing to add records no drop', async () => {
	const fake = fakeDeps();
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([], { errors: ['2 dropped items could not be read as files.'] });
	await queue.idle();
	assert.deepEqual(queue.getState().drops, []);
	await queue.addDrop([candidate('a.md')]);
	await queue.idle();
	assert.equal(queue.getState().drops.length, 1);
	queue.dispose();
	assert.deepEqual(queue.getState().drops, []);
});

// ── The list ────────────────────────────────────────────────────────────────

test('the upload list holds the drop summary above its rows, and renders nothing without rows', () => {
	const one = row('u1', 'docs/a.md', 'done', { chunks: 7 });
	const html = render(h(UploadList, { rows: [one], notes: [], onClearFinished: () => undefined }));
	const at = html.search(/<[a-z]+[^>]*data-component="IngestSummary"/);
	assert.ok(at >= 0, 'the summary is mounted');
	assert.ok(at < html.indexOf('aria-label="Uploads"'), 'above the rows');
	if (html.slice(at, html.indexOf('>', at)).includes('data-placeholder')) assert.match(html.slice(at, at + 600), /Not built yet/);
	assert.equal(render(h(UploadList, { rows: [], notes: [], onClearFinished: () => undefined })), '');
});
