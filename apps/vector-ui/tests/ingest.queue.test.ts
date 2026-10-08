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
// ingest.queue — the upload queue's lifecycle around the happy path
// =============================================================================
//
// Counting after an upload, stores that cannot be probed, sends that never
// start, drops that overlap, identity changes in the middle of an upload,
// and two connections uploading files of the same name at once.
// =============================================================================

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ExplorerToolError } from 'shared/explorer';
import type { ISendFile } from 'shared/explorer';
import { objectIdForPath } from '../src/vector/objectId';
import { uploadLabel } from '../src/vector/uploads';
import type { DropCandidate } from '../src/vector/uploads';
import { RECOUNT_DELAY_MS, createIngestQueue } from '../src/ingest/ingestQueue';
import type { IngestDeps } from '../src/ingest/ingestQueue';
import { createNameLocks } from '../src/ingest/nameLocks';
import type { CallOutcome } from '../src/chat/toolCalls';

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

/**
 * Plain fake dependencies: nothing stored, every upload completes, 2 chunks each.
 *
 * @param overrides - Fields to replace.
 * @returns The deps and what they saw.
 */
function fakeDeps(overrides: Partial<IngestDeps> = {}): { deps: IngestDeps; sent: string[][]; changed: string[][]; announced: string[]; tools: string[]; slept: number[] } {
	const sent: string[][] = [];
	const changed: string[][] = [];
	const announced: string[] = [];
	const tools: string[] = [];
	const slept: number[] = [];
	const deps: IngestDeps = {
		canProbe: true,
		canCount: true,
		async callTool(tool, input): Promise<CallOutcome> {
			tools.push(tool);
			if (tool === 'chunks') return { ok: false, code: 'NOT_FOUND', message: 'not stored', kind: null, error: null };
			const id = (input.object_ids as string[])[0];
			return { ok: true, value: { success: true, items: [{ objectId: id, chunks: 2 }] } };
		},
		async sendFiles(files: ISendFile[]) {
			sent.push(files.map((file) => String(file.objinfo?.name)));
			return files.map((file) => ({ action: 'complete', filepath: file.file.name, bytes_sent: file.file.size, file_size: file.file.size, upload_time: 0 }));
		},
		onDocumentsChanged(ids) {
			changed.push([...ids]);
		},
		announce(message) {
			announced.push(message);
		},
		async sleep(ms) {
			slept.push(ms);
		},
		locks: createNameLocks(),
		...overrides,
	};
	return { deps, sent, changed, announced, tools, slept };
}

test('queue: a finished upload is counted and the console is told which documents changed', async () => {
	const fake = fakeDeps();
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('a.md'), candidate('b.md')]);
	await queue.idle();
	assert.deepEqual(fake.changed, [[objectIdForPath('a.md'), objectIdForPath('b.md')]]);
	assert.deepEqual(
		queue.getState().rows.map((row) => uploadLabel(row)),
		['2 chunks added', '2 chunks added']
	);
	assert.ok(fake.announced.includes('a.md: 2 chunks added'));
	assert.equal(queue.getState().busy, false);
});

test('queue: a document the store does not list yet is asked for once more, then reported honestly', async () => {
	let documentsCalls = 0;
	const fake = fakeDeps({
		async callTool(tool): Promise<CallOutcome> {
			if (tool === 'chunks') return { ok: false, code: 'NOT_FOUND', message: 'not stored', kind: null, error: null };
			documentsCalls += 1;
			return { ok: true, value: { success: true, items: [] } };
		},
	});
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('late.md')]);
	await queue.idle();
	assert.equal(documentsCalls, 2);
	assert.deepEqual(fake.slept, [RECOUNT_DELAY_MS]);
	const row = queue.getState().rows[0];
	assert.equal(row.status, 'done');
	assert.equal(uploadLabel(row), 'Sent, but the store does not list it yet. Refresh in a moment.');
});

test('queue: zero chunks, an uncountable store and a failed count each read as what they are', async () => {
	const answers: Record<string, CallOutcome> = {
		[objectIdForPath('empty.pdf')]: { ok: true, value: { success: true, items: [{ objectId: objectIdForPath('empty.pdf'), chunks: 0 }] } },
		[objectIdForPath('pine.md')]: { ok: true, value: { success: true, items: [{ objectId: objectIdForPath('pine.md'), chunks: null }] } },
		[objectIdForPath('err.md')]: { ok: false, code: 'STORE_ERROR', message: 'OperationalError: the store did not answer', kind: null, error: null },
	};
	const fake = fakeDeps({
		async callTool(tool, input): Promise<CallOutcome> {
			if (tool === 'chunks') return { ok: false, code: 'NOT_FOUND', message: 'not stored', kind: null, error: null };
			return answers[(input.object_ids as string[])[0]];
		},
	});
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('empty.pdf'), candidate('pine.md'), candidate('err.md')]);
	await queue.idle();
	assert.deepEqual(
		queue.getState().rows.map((row) => uploadLabel(row)),
		['No chunks were stored: the file may have no text the parser can read.', 'Added. This store does not report chunk counts.', 'Added. The chunk count could not be read: OperationalError: the store did not answer']
	);
});

test('queue: a store that cannot be probed asks once per drop before sending', async () => {
	const fake = fakeDeps({ canProbe: false });
	const queue = createIngestQueue(fake.deps);
	const drop = queue.addDrop([candidate('x.md'), candidate('y.md')]);
	await queue.waitFor((state) => state.confirm !== null);
	const confirm = queue.getState().confirm;
	assert.equal(confirm?.items.length, 2);
	assert.ok(confirm?.message.some((line) => /x\.md: could not check \(this store cannot look documents up\)/.test(line)));
	assert.ok(!fake.tools.includes('chunks'));
	queue.answerConfirm(true);
	await drop;
	await queue.idle();
	assert.deepEqual(fake.sent, [['x.md', 'y.md']]);
});

test('queue: a probe that fails is a question, never a silent overwrite', async () => {
	const fake = fakeDeps({
		async callTool(tool, input): Promise<CallOutcome> {
			if (tool === 'chunks') return { ok: false, code: null, message: 'chunks reported a failure', kind: 'store', error: new ExplorerToolError({ kind: 'store', tool: 'chunks', message: 'chunks reported a failure' }) };
			return { ok: true, value: { success: true, items: [{ objectId: (input.object_ids as string[])[0], chunks: 1 }] } };
		},
	});
	const queue = createIngestQueue(fake.deps);
	const drop = queue.addDrop([candidate('q.md')]);
	await queue.waitFor((state) => state.confirm !== null);
	assert.equal(queue.getState().confirm?.confirmLabel, 'Send anyway');
	assert.equal(fake.sent.length, 0);
	queue.answerConfirm(false);
	await drop;
	await queue.idle();
	assert.equal(fake.sent.length, 0);
	assert.equal(queue.getState().rows[0].status, 'cancelled');
});

test('queue: a send that never starts fails every file of the call with the reason', async () => {
	const fake = fakeDeps({
		async sendFiles() {
			throw new ExplorerToolError({ kind: 'unavailable', tool: 'sendFiles', message: "No running ingest source for pipeline 'Vector demo'. Start it and retry." });
		},
	});
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('a.md'), candidate('b.md')]);
	await queue.idle();
	for (const row of queue.getState().rows) {
		assert.equal(row.status, 'failed');
		assert.equal(row.message, "Not sent: this pipeline's Ingest source is not running. Start its dropper source and try again.");
	}
	assert.deepEqual(fake.changed, []);
});

test('queue: refused files get a row and an announcement; traversal notes are shown', async () => {
	const fake = fakeDeps();
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('ok.md'), candidate('bad.exe')], { skipped: ['x/.DS_Store', 'x/Thumbs.db'], errors: ['Could not read x/broken.pdf.'], truncated: true });
	await queue.idle();
	const rows = queue.getState().rows;
	assert.deepEqual(
		rows.map((row) => [row.path, row.status]),
		[
			['ok.md', 'done'],
			['bad.exe', 'refused'],
		]
	);
	assert.match(uploadLabel(rows[1]), /\.exe files are not supported/);
	assert.ok(fake.announced.includes('1 file was not added; the list says why.'));
	assert.deepEqual(queue.getState().notes, ['Skipped 2 hidden or system files.', 'Could not read x/broken.pdf.', 'More than 1,000 files were dropped; only the first 1,000 were read.']);
});

test('queue: a second drop of a path still being added is refused; drops are handled in order', async () => {
	const gate = deferred<void>();
	const fake = fakeDeps({
		async sendFiles(files: ISendFile[]) {
			await gate.promise;
			return files.map((file) => ({ action: 'complete', filepath: file.file.name, bytes_sent: 1, file_size: 1, upload_time: 0 }));
		},
	});
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('slow.md')]);
	await queue.addDrop([candidate('slow.md'), candidate('other.md')]);
	const rows = queue.getState().rows;
	assert.deepEqual(
		rows.map((row) => [row.path, row.status]),
		[
			['slow.md', 'queued'],
			['slow.md', 'refused'],
			['other.md', 'queued'],
		]
	);
	assert.match(rows[1].message ?? '', /already being added/);
	gate.resolve();
	await queue.idle();
	assert.deepEqual(
		queue.getState().rows.map((row) => row.status),
		['done', 'refused', 'done']
	);
});

test('queue: dispose in the middle of an upload forgets everything and ignores the late result', async () => {
	const gate = deferred<void>();
	const fake = fakeDeps({
		async sendFiles(files: ISendFile[]) {
			await gate.promise;
			return files.map((file) => ({ action: 'complete', filepath: file.file.name, bytes_sent: 1, file_size: 1, upload_time: 0 }));
		},
	});
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('a.md')]);
	queue.dispose();
	assert.deepEqual(queue.getState().rows, []);
	gate.resolve();
	await new Promise((resolve) => setTimeout(resolve, 5));
	assert.deepEqual(queue.getState().rows, []);
	assert.deepEqual(fake.changed, []);
	assert.equal(fake.tools.filter((tool) => tool === 'documents').length, 0);
	queue.handleEvent({ action: 'write', filepath: 'a.md', bytes_sent: 1, file_size: 1, upload_time: 0 });
	assert.deepEqual(queue.getState().rows, []);
	await queue.addDrop([candidate('b.md')]);
	assert.deepEqual(queue.getState().rows, []);
});

test('queue: dispose while the replace question is open sends nothing', async () => {
	const fake = fakeDeps({ canProbe: false });
	const queue = createIngestQueue(fake.deps);
	const drop = queue.addDrop([candidate('a.md')]);
	await queue.waitFor((state) => state.confirm !== null);
	queue.dispose();
	await drop;
	assert.equal(fake.sent.length, 0);
	assert.equal(queue.getState().confirm, null);
});

test('queue: clearFinished keeps only rows still in progress', async () => {
	const fake = fakeDeps();
	const queue = createIngestQueue(fake.deps);
	await queue.addDrop([candidate('a.md'), candidate('b.exe')]);
	await queue.idle();
	queue.clearFinished();
	assert.deepEqual(queue.getState().rows, []);
	assert.deepEqual(queue.getState().notes, []);
});

test('name locks: two connections sending report.pdf take turns; different names run side by side', async () => {
	const locks = createNameLocks();
	const order: string[] = [];
	const gates = { a: deferred<void>(), b: deferred<void>() };
	const queueFor = (label: 'a' | 'b'): ReturnType<typeof createIngestQueue> =>
		createIngestQueue(
			fakeDeps({
				locks,
				async sendFiles(files: ISendFile[]) {
					order.push(`${label}:start:${files.map((file) => file.file.name).join(',')}`);
					await gates[label].promise;
					order.push(`${label}:end`);
					return files.map((file) => ({ action: 'complete', filepath: file.file.name, bytes_sent: 1, file_size: 1, upload_time: 0 }));
				},
			}).deps
		);
	const a = queueFor('a');
	const b = queueFor('b');
	await a.addDrop([candidate('x/report.pdf')]);
	await b.addDrop([candidate('y/report.pdf')]);
	await new Promise((resolve) => setTimeout(resolve, 5));
	assert.deepEqual(order, ['a:start:report.pdf']);
	assert.deepEqual(locks.held(), ['report.pdf']);
	gates.b.resolve();
	gates.a.resolve();
	await a.idle();
	await b.idle();
	assert.deepEqual(order, ['a:start:report.pdf', 'a:end', 'b:start:report.pdf', 'b:end']);
	assert.deepEqual(locks.held(), []);

	const free = createNameLocks();
	const first = await free.acquire(['one.md']);
	let secondGranted = false;
	void free.acquire(['two.md']).then(() => {
		secondGranted = true;
	});
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.equal(secondGranted, true);
	first();
	first();
	assert.deepEqual(free.held(), ['two.md']);
});
