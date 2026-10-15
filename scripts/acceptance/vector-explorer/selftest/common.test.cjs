// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Self-test for browser/common.cjs and browser/ui.cjs, without a browser or an
 * engine: objectId, the PDF writer, the B4 privacy property, the pairing of
 * the page's tool calls with their answers, and the selector table.
 * Run: node --test scripts/acceptance/vector-explorer/selftest/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const C = require('../browser/common.cjs');
const { CONSOLE, MAP } = require('../browser/ui.cjs');

const DIM = 384;
const vec = (seed, dim = DIM) => Array.from({ length: dim }, (_, i) => Math.sin(seed + i) / 3);

test('objectId matches the engine (uuid5 of the upload name)', () => {
	// Observed on the engine (and pinned in test_seed_legacy.py).
	assert.strictEqual(C.objectId('/srv/legacy/ops/memo_q2.txt'), '9f2bee29-b134-547e-9ba8-2ff9f8dd0f42');
});

test('makePdf writes a PDF whose cross-reference table points at its objects', () => {
	const pdf = C.makePdf('Report (alpha) for the lane').toString('latin1');
	assert.ok(pdf.startsWith('%PDF-1.4\n'));
	const startxref = Number(/startxref\n(\d+)\n%%EOF/.exec(pdf)[1]);
	assert.strictEqual(pdf.slice(startxref, startxref + 4), 'xref');
	const offsets = [...pdf.slice(startxref).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]));
	assert.strictEqual(offsets.length, 5);
	offsets.forEach((o, i) => assert.ok(pdf.slice(o).startsWith(`${i + 1} 0 obj`), `object ${i + 1}`));
	assert.ok(pdf.includes('(Report \\(alpha\\) for the lane) Tj'));
});

let seq = 0;
const req = (tool, input = {}, nodeId = 'store_1') => ({ dir: 'sent', msg: { type: 'request', seq: ++seq, command: 'rrext_process', arguments: { subcommand: 'tool', tool, nodeId, input } } });
const res = (request, result) => ({ dir: 'received', msg: { type: 'response', request_seq: request.msg.seq, success: true, body: { result } } });
const evt = (event, body) => ({ dir: 'received', msg: { type: 'event', event, body } });
const pair = (tool, input, result, nodeId) => {
	const r = req(tool, input, nodeId);
	return [r, res(r, result)];
};

test('privacy: embed answers and the query vector they return are allowed', () => {
	const v = vec(1);
	const frames = [...pair('embed', { texts: ['q'] }, { vectors: [v] }, 'embed_1'), ...pair('search', { vector: v, top_k: 3 }, { results: [] })];
	assert.deepStrictEqual(C.privacyViolations(frames, DIM), []);
});

test('privacy: a request with a vector no embed answer returned is a violation', () => {
	const frames = [...pair('embed', {}, { vectors: [vec(1)] }, 'embed_1'), req('search', { vector: vec(2) })];
	assert.strictEqual(C.privacyViolations(frames, DIM).length, 1);
});

test('privacy: raw vectors in any other answer are a violation; vectors may carry two', () => {
	assert.strictEqual(C.privacyViolations(pair('documents', {}, { items: [{ embedding: vec(3) }] }), DIM).length, 1);
	assert.deepStrictEqual(C.privacyViolations(pair('vectors', {}, { items: [{ values: vec(1) }, { values: vec(2) }] }), DIM), []);
	assert.strictEqual(C.privacyViolations(pair('vectors', {}, { items: [vec(1), vec(2), vec(3)].map((values) => ({ values })) }), DIM).length, 1);
});

test('privacy: sample columns of n values are not vectors, other keys in a sample answer are', () => {
	const column = vec(5);
	assert.deepStrictEqual(C.privacyViolations(pair('sample', {}, { n: DIM, points: { x: column, y: column }, density: column }), DIM), []);
	assert.strictEqual(C.privacyViolations(pair('sample', {}, { n: DIM, points: { x: column }, raw: [column] }), DIM).length, 1);
	// Integer arrays (ids, lengths) are not embeddings.
	assert.deepStrictEqual(C.privacyViolations(pair('sample', {}, { n: 1000, points: { doc: Array.from({ length: DIM }, (_, i) => i) } }), DIM), []);
	assert.deepStrictEqual(C.privacyViolations(pair('documents', {}, { ids: Array.from({ length: DIM }, (_, i) => i) }), DIM), []);
});

test("privacy: a column path is exempt only when its length is the answer's own count", () => {
	const stray = vec(6);
	// A 1,000-point sample has columns of 1,000: a dimension-long float array under points is a vector.
	assert.strictEqual(C.privacyViolations(pair('sample', {}, { n: 1000, points: { vectors: stray } }), DIM).length, 1);
	assert.strictEqual(C.privacyViolations(pair('sample', {}, { n: 1000, density: stray }), DIM).length, 1);
	assert.strictEqual(C.privacyViolations(pair('sample', {}, { points: { x: stray } }), DIM).length, 1, 'no n: nothing is exempt');
	// knn.sims holds one similarity per edge: as many as knn.cols.
	const cols = Array.from({ length: DIM }, (_, i) => i % 7);
	assert.deepStrictEqual(C.privacyViolations(pair('sample', {}, { n: 32, knn: { cols, sims: stray } }), DIM), []);
	assert.strictEqual(C.privacyViolations(pair('sample', {}, { n: 32, knn: { cols: cols.slice(1), sims: stray } }), DIM).length, 1);
});

test('privacy: project similarities follow their sample, neighbors scores their scope', () => {
	const stray = vec(8);
	const [s1, s1Res] = pair('sample', { n: DIM }, { sample_id: 's-7-aaaaaaaa', n: DIM });
	const [s2, s2Res] = pair('sample', { n: 1000 }, { sample_id: 's-7-bbbbbbbb', n: 1000 });
	const ok = pair('project', { sample_id: 's-7-aaaaaaaa', vector: [0.5] }, { similarities: stray });
	assert.deepStrictEqual(C.privacyViolations([s1, s1Res, s2, s2Res, ...ok], DIM), []);
	const wrong = pair('project', { sample_id: 's-7-bbbbbbbb', vector: [0.5] }, { similarities: stray });
	assert.strictEqual(C.privacyViolations([s1, s1Res, s2, s2Res, ...wrong], DIM).length, 1);
	const unknown = pair('project', { sample_id: 's-7-cccccccc', vector: [0.5] }, { similarities: stray });
	assert.strictEqual(C.privacyViolations(unknown, DIM).length, 1);
	const keys = Array.from({ length: DIM }, (_, i) => ['x', i]);
	assert.deepStrictEqual(C.privacyViolations(pair('neighbors', { key: ['x', 0], scope_keys: keys }, { scores: stray }), DIM), []);
	assert.strictEqual(C.privacyViolations(pair('neighbors', { key: ['x', 0] }, { scores: stray }), DIM).length, 1);
});

test('privacy: the length checked is dialect.dimension, not a fixed 384', () => {
	const wide = vec(7, 768);
	assert.strictEqual(C.privacyViolations(pair('chunks', {}, { items: [{ embedding: wide }] }), 768).length, 1);
	assert.deepStrictEqual(C.privacyViolations(pair('chunks', {}, { items: [{ embedding: vec(7) }] }), 768), []);
	// Without a dimension the property cannot hold.
	assert.strictEqual(C.privacyViolations([], null).length, 1);
	assert.strictEqual(C.privacyViolations([], 0).length, 1);
});

test('privacy: an event (chat or upload status) carrying a vector is a violation', () => {
	assert.strictEqual(C.privacyViolations([evt('apaevt_chat', { documents: [{ embedding: vec(2) }] })], DIM).length, 1);
	assert.deepStrictEqual(C.privacyViolations([evt('apaevt_status_upload', { name: 'a.md', state: 'done' })], DIM), []);
});

test('exchanges pair each tool call of the page with its answer', () => {
	const [a, aRes] = pair('sample', { n: 10, mode: 'light' }, { success: true, n: 10 });
	const b = req('neighbors', { key: ['x', 0], k: 12 });
	const capture = { sockets: 1, frames: [a, b, aRes] };
	const samples = C.exchanges(capture, 'sample');
	assert.strictEqual(samples.length, 1);
	assert.deepStrictEqual(samples[0].input, { n: 10, mode: 'light' });
	assert.deepStrictEqual(samples[0].result, { success: true, n: 10 });
	const pending = C.exchanges(capture, 'neighbors');
	assert.strictEqual(pending[0].result, undefined);
	assert.strictEqual(C.exchanges(capture, 'sample', 1).length, 0);
});

test('waitForExchange gives up at once on a page that opened no WebSocket', async () => {
	await assert.rejects(C.waitForExchange({ sockets: 0, frames: [] }, 'sample', { timeout: 60000 }), /no WebSocket/);
});

test('isUpload recognises the SDK upload requests only', () => {
	assert.ok(C.isUpload({ command: 'rrext_process', arguments: { subcommand: 'open' } }));
	assert.ok(C.isUpload({ command: 'rrext_process', arguments: { subcommand: 'write' } }));
	assert.ok(!C.isUpload({ command: 'rrext_process', arguments: { subcommand: 'tool', tool: 'chunks' } }));
	assert.ok(!C.isUpload(null));
});

test("the selector table holds the app's wording", () => {
	assert.strictEqual(CONSOLE.trash('C:/demo/a.md'), 'Remove C:/demo/a.md from the database');
	assert.ok(MAP.nativeGraph('Qdrant').test('… · neighbour graph computed by Qdrant · …'));
	assert.ok(MAP.nodeGraph.test('… · neighbour graph computed by the store node · …'));
	assert.ok(MAP.layoutNotBetter.test('Neighbour layout did not improve on PCA for this sample'));
	assert.ok(MAP.announcement(11, 1000).test('Point 12 of 1,000: C:/demo/a.md, chunk 3'));
	assert.ok(!MAP.announcement(1, 1000).test('Point 12 of 1,000: C:/demo/a.md, chunk 3'));
	assert.deepStrictEqual(MAP.tableRows.exec('Rows 1–100 of 1,318').slice(1), ['1', '100', '1,318']);
	assert.strictEqual(Object.keys(MAP.attr).length, new Set(Object.values(MAP.attr)).size);
});

test('a stats figure is a number only once the strip shows one', () => {
	assert.strictEqual(C.figureNumber('1,500'), 1500);
	assert.strictEqual(C.figureNumber(' 40 '), 40);
	assert.strictEqual(C.figureNumber('0'), 0);
	// Pending, unknown, or not a count: no number (never 0).
	for (const text of ['…', '—', '', null, undefined, '1,50', '12 MB', 'Documents0 loaded']) assert.strictEqual(C.figureNumber(text), null, String(text));
});

test("an upload is done only when the row of that file says so (not another row's count)", () => {
	const rows = [
		{ path: 'lane-1/a/report.pdf', status: 'done' },
		{ path: 'lane-1/b/report.pdf', status: 'processing' },
		{ path: 'lane-1/nested/deeper/note.md', status: 'done' },
	];
	assert.ok(C.uploadsDone(rows, ['lane-1/a/report.pdf', 'lane-1/nested/deeper/note.md']));
	assert.ok(!C.uploadsDone(rows, ['lane-1/a/report.pdf', 'lane-1/b/report.pdf']), 'one of the same-named files is still processing');
	assert.ok(!C.uploadsDone(rows, ['lane-1/c/report.pdf']), 'no row for that file');
	assert.ok(!C.uploadsDone([], ['x.md']));
});

test("the selectors the lanes read exist in the app's source", () => {
	const fs = require('fs');
	const path = require('path');
	const src = (file) => fs.readFileSync(path.join(__dirname, '..', '..', '..', '..', 'apps', 'vector-ui', 'src', file), 'utf8');
	assert.match(src('components/StatsStrip.tsx'), /data-figure=\{f\.key\}/, 'each stats figure carries data-figure');
	assert.match(src('components/UploadList.tsx'), /aria-label="Uploads"[\s\S]*<li key=\{row\.id\} style=\{S\.row\} data-status=\{row\.status\}>[\s\S]*title=\{row\.path\}/, 'each upload row carries data-status and its path as a title');
	assert.match(src('components/DocumentDirectory.tsx'), new RegExp(`placeholder="${CONSOLE.filterPaths}"`));
	assert.match(src('components/SourcesPanel.tsx'), new RegExp(`aria-label="${CONSOLE.sources}"`));
	assert.match(src('components/SourcesPanel.tsx'), /aria-label=\{`Open \$\{path\} at chunk \$\{source\.chunkId\}`\}/);
	assert.ok(CONSOLE.sourceOpen.test('Open C:/demo/a.md at chunk 3'));
	assert.deepStrictEqual(CONSOLE.sourceTarget.exec('Open C:/demo/a b.md at chunk 12').slice(1), ['C:/demo/a b.md', '12']);
	assert.match(src('vector/confirm.ts'), /prompt: `Type the table name '\$\{table\}' to confirm\.`/);
	assert.deepStrictEqual(CONSOLE.typedConfirm.exec("Type the table name 'vx_demo_rr' to confirm.").slice(1), ['vx_demo_rr']);
	assert.match(src('views/DocumentView.tsx'), /data-document=\{objectId\}/);
	assert.match(src('views/DocumentView.tsx'), /data-chunk=\{chunk\.chunkId\}/);
	assert.match(src('views/MapView.tsx'), new RegExp(`className="${MAP.root.slice(1)}"`));
	assert.match(src('VectorApp.tsx'), new RegExp(`label: '${CONSOLE.connectionsTab}'`), "the landing's shell tab label");
});
