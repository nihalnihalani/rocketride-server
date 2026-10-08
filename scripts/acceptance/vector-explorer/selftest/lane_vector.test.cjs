// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Self-test for browser/lane_vector.cjs, without a browser or an engine: its
 * helpers (objectId, the PDF writer, the privacy check) and its verdicts on an
 * empty stand-in page, where every step must FAIL.
 * Run: node --test scripts/acceptance/vector-explorer/selftest/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { runWithStandIn } = require('./stand_in.cjs');
const lane = require('../browser/lane_vector.cjs');

const DIM = 384;
const vec = (seed) => Array.from({ length: DIM }, (_, i) => Math.sin(seed + i) / 3);

test('objectId matches the engine (uuid5 of the upload name)', () => {
	// Observed on the engine (and pinned in test_seed_legacy.py).
	assert.strictEqual(lane.objectId('/srv/legacy/ops/memo_q2.txt'), '9f2bee29-b134-547e-9ba8-2ff9f8dd0f42');
});

test('makePdf writes a PDF whose cross-reference table points at its objects', () => {
	const pdf = lane.makePdf('Report (alpha) for the lane').toString('latin1');
	assert.ok(pdf.startsWith('%PDF-1.4\n'));
	const startxref = Number(/startxref\n(\d+)\n%%EOF/.exec(pdf)[1]);
	assert.strictEqual(pdf.slice(startxref, startxref + 4), 'xref');
	const offsets = [...pdf.slice(startxref).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]));
	assert.strictEqual(offsets.length, 5);
	offsets.forEach((o, i) => assert.ok(pdf.slice(o).startsWith(`${i + 1} 0 obj`), `object ${i + 1}`));
	assert.ok(pdf.includes('(Report \\(alpha\\) for the lane) Tj'));
});

const req = (seq, tool, input = {}) => ({ dir: 'sent', msg: { type: 'request', seq, command: 'rrext_process', arguments: { subcommand: 'tool', tool, nodeId: 'store_1', input } } });
const res = (seq, result) => ({ dir: 'received', msg: { type: 'response', request_seq: seq, success: true, body: { result } } });

test('privacy: embed answers and the query vector they return are allowed', () => {
	const v = vec(1);
	const frames = [req(1, 'embed', { texts: ['q'] }), res(1, { vectors: [v] }), req(2, 'search', { vector: v, top_k: 3 }), res(2, { results: [] })];
	assert.deepStrictEqual(lane.privacyViolations(frames), []);
});

test('privacy: a request with a vector no embed answer returned is a violation', () => {
	const frames = [req(1, 'embed'), res(1, { vectors: [vec(1)] }), req(2, 'search', { vector: vec(2) })];
	assert.strictEqual(lane.privacyViolations(frames).length, 1);
});

test('privacy: raw vectors in any other answer are a violation; vectors may carry two', () => {
	assert.strictEqual(lane.privacyViolations([req(1, 'documents'), res(1, { items: [{ embedding: vec(3) }] })]).length, 1);
	assert.deepStrictEqual(lane.privacyViolations([req(1, 'vectors'), res(1, { items: [{ values: vec(1) }, { values: vec(2) }] })]), []);
	assert.strictEqual(lane.privacyViolations([req(1, 'vectors'), res(1, { items: [vec(1), vec(2), vec(3)].map((values) => ({ values })) })]).length, 1);
});

test('privacy: sample columns of n values are not vectors, other keys in a sample answer are', () => {
	const column = vec(5);
	assert.deepStrictEqual(lane.privacyViolations([req(1, 'sample'), res(1, { points: { x: column, y: column }, density: column })]), []);
	assert.strictEqual(lane.privacyViolations([req(1, 'sample'), res(1, { points: { x: column }, raw: [column] })]).length, 1);
	// Integer arrays (ids, lengths) are not embeddings.
	assert.deepStrictEqual(lane.privacyViolations([req(1, 'documents'), res(1, { ids: Array.from({ length: DIM }, (_, i) => i) })]), []);
});

let run;
const standIn = () => (run ||= runWithStandIn('lane_vector.cjs', ['qdrant'], 'lane_vector.json'));

test('lane_vector: every step fails on an empty page', () => {
	const { data, stdout } = standIn();
	assert.ok(data.length >= 11, `only ${data.length} steps ran:\n${stdout}`);
	const passed = data.filter((r) => r.status === 'PASS');
	assert.deepStrictEqual(passed, [], `steps passed without observing anything: ${JSON.stringify(passed)}`);
});

test('lane_vector: exits non-zero when a step failed', () => {
	assert.notStrictEqual(standIn().status, 0);
});
