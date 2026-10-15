// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// DEDUPE: near-duplicate pairs at a threshold, groups, keep policies, the queue
// =============================================================================
//
// The duplicates queue is computed in the browser from what the sample holds:
// the node's `duplicates` and every kNN pair at or above the threshold, so
// moving the threshold re-groups without a call. Pairs make point groups
// (union-find); point groups over the same documents make one queue group;
// a group inside one document is listed apart and never offers removal. A
// keep policy picks one document per group and queues the others, except a
// document another group keeps. Reviewed documents live in the connection's
// 'reviewed documents' cache, cleared on a change of identity.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import type { IDocumentItem, IDuplicatePair, IKnnBlock, ISampleResult } from '../src/contract/types';
import { reviewedDocuments } from '../src/adapters/connections';
import { connectionCaches } from '../src/adapters/explorer';
import { KEEP_POLICIES, THRESHOLD_DEFAULT, THRESHOLD_MAX, THRESHOLD_MIN, applyPolicy, dedupeView, docInfo, duplicateGroupOf, groupOf, groups, keepOf, markReviewed, pairsAt, queueInit, queueReducer, queued, reviewedOf, unmarkReviewed } from '../src/map/dedupe';
import { loadSample } from './support/map.samples';

// =============================================================================
// A SMALL SAMPLE BUILDER
// =============================================================================

interface IPointSpec {
	doc: number;
	chunk: number;
}

/**
 * A sample answer from documents, points and explicit kNN rows.
 *
 * @param docs - [objectId, path, chunks] per document.
 * @param points - Document index and chunk id per point.
 * @param rows - Per point: [neighbour, similarity] pairs, nearest first.
 * @param duplicates - The node's duplicate pairs.
 * @returns The answer.
 */
function sampleOf(docs: Array<[string, string, number | null]>, points: IPointSpec[], rows: Array<Array<[number, number]>>, duplicates: IDuplicatePair[] = []): ISampleResult {
	const knn: IKnnBlock = { k: Math.max(0, ...rows.map((r) => r.length)), offsets_row: [0], cols: [], sims: [] };
	for (const row of rows) {
		for (const [j, sim] of row) {
			knn.cols.push(j);
			knn.sims.push(sim);
		}
		knn.offsets_row.push(knn.cols.length);
	}
	const n = points.length;
	return {
		success: true,
		sample_id: 's-7-test',
		expires_in_s: 600,
		n,
		n_requested: n,
		mode: 'detailed',
		of: { chunks: n, documents: docs.length },
		strategy_used: 'stratified',
		biased: false,
		knn_source: 'node',
		metric: 'cosine',
		dimension: 8,
		docs: docs.map(([objectId, p, chunks], i) => ({ i, objectId, path: p, chunks, in_sample: points.filter((pt) => pt.doc === i).length })),
		points: { doc: points.map((p) => p.doc), chunk: points.map((p) => p.chunk), x: points.map(() => 0), y: points.map(() => 0), len: points.map(() => 100), snip: points.map(() => 'text'), pinned: points.map(() => 0) },
		knn,
		density: points.map(() => 0.5),
		outliers: [],
		duplicates,
		pca: { explained: [0.5, 0.3] },
		took_ms: 1,
	};
}

/** A directory row. */
function row(objectId: string, p: string, chunks: number | null, ingestedAt: string | null, size: number | null = null): IDocumentItem {
	return { objectId, path: p, chunks, has_first_chunk: true, tables: 0, deleted: false, nodeId: null, size, modifyTime: null, ingestedAt, pointId: null };
}

// Documents A (handbook), B (its revision), C (a kestrel guide), D (its copy), E (unrelated).
const DOCS: Array<[string, string, number | null]> = [
	['oa', 'C:/demo/handbooks/falcon_handbook.md', 3],
	['ob', 'C:/demo/handbooks/falcon_handbook_rev2.md', 3],
	['oc', 'C:/demo/field/kestrel_field_guide.md', 2],
	['od', 'C:/demo/archive/kestrel_field_guide_copy.md', 2],
	['oe', 'C:/demo/ops/memo_q1.txt', 4],
];
// Points: A#0 A#1 B#0 B#1 C#0 D#0 E#0 E#2 (E#0 and E#2 repeat a paragraph inside E).
const POINTS: IPointSpec[] = [
	{ doc: 0, chunk: 0 },
	{ doc: 0, chunk: 1 },
	{ doc: 1, chunk: 0 },
	{ doc: 1, chunk: 1 },
	{ doc: 2, chunk: 0 },
	{ doc: 3, chunk: 0 },
	{ doc: 4, chunk: 0 },
	{ doc: 4, chunk: 2 },
];
const ROWS: Array<Array<[number, number]>> = [
	[
		[2, 0.995],
		[1, 0.62],
	],
	[
		[3, 0.981],
		[0, 0.62],
	],
	[
		[0, 0.995],
		[3, 0.6],
	],
	[
		[1, 0.981],
		[2, 0.6],
	],
	[
		[5, 0.93],
		[6, 0.4],
	],
	[
		[4, 0.93],
		[6, 0.41],
	],
	[
		[7, 0.99],
		[4, 0.4],
	],
	[
		[6, 0.99],
		[5, 0.41],
	],
];
// The node reported C#0 ↔ D#0 at 0.975 although its kNN rows say 0.93 (a pair only in sample.duplicates).
const NODE_ONLY: IDuplicatePair = { a: 4, b: 5, sim: 0.975 };
const SMALL = sampleOf(DOCS, POINTS, ROWS, [{ a: 0, b: 2, sim: 0.995 }, NODE_ONLY]);

// =============================================================================
// PAIRS
// =============================================================================

test('pairsAt: the node pairs and every kNN pair at or above the threshold, each once (a < b, highest similarity), most similar first', () => {
	assert.deepEqual(pairsAt(SMALL, 0.97), [
		{ a: 0, b: 2, sim: 0.995 },
		{ a: 6, b: 7, sim: 0.99 },
		{ a: 1, b: 3, sim: 0.981 },
		{ a: 4, b: 5, sim: 0.975 },
	]);
	assert.deepEqual(
		pairsAt(SMALL, 0.985).map((p) => [p.a, p.b]),
		[
			[0, 2],
			[6, 7],
		],
		'a higher threshold drops the weaker pairs, the node pair included'
	);
	assert.equal(pairsAt(SMALL, THRESHOLD_MIN).length, 4, 'at 0.90 the kNN pair C#0 ↔ D#0 (0.93) is there either way');
	const selfLoop = sampleOf(DOCS.slice(0, 1), [{ doc: 0, chunk: 0 }], [[[0, 1]]]);
	assert.deepEqual(pairsAt(selfLoop, 0.9), [], 'a point is never its own duplicate');
});

test("pairsAt on the demo sample at 0.97 is exactly the node's list", () => {
	const demo = loadSample('sample_demo_1000.json');
	const key = (p: IDuplicatePair): string => `${p.a}-${p.b}-${p.sim}`;
	assert.deepEqual(pairsAt(demo, 0.97).map(key).sort(), demo.duplicates.map(key).sort());
	assert.equal(pairsAt(demo, THRESHOLD_MAX).length, 8, 'every planted pair is above 0.995');
});

// =============================================================================
// GROUPS
// =============================================================================

test('groups: union-find over the pairs, transitive, numbered by size (ties by first point), with the similarity range inside', () => {
	const found = groups([
		{ a: 5, b: 9, sim: 0.98 },
		{ a: 1, b: 2, sim: 0.99 },
		{ a: 2, b: 3, sim: 0.975 },
		{ a: 7, b: 8, sim: 0.97 },
	]);
	assert.deepEqual(found, [
		{ id: 0, points: [1, 2, 3], simMin: 0.975, simMax: 0.99 },
		{ id: 1, points: [5, 9], simMin: 0.98, simMax: 0.98 },
		{ id: 2, points: [7, 8], simMin: 0.97, simMax: 0.97 },
	]);
	assert.deepEqual(groups([]), []);
	assert.deepEqual([...groupOf(found, 10)], [-1, 0, 0, 0, -1, 1, -1, 2, 2, 1]);
});

test('a path of 500 pairs is one group (union-find, not a bounded number of passes)', () => {
	const pairs = Array.from({ length: 499 }, (_, i) => ({ a: i, b: i + 1, sim: 0.99 }));
	const found = groups(pairs);
	assert.equal(found.length, 1);
	assert.equal(found[0]!.points.length, 500);
});

test('the queue groups documents: point groups over the same documents merge, a group inside one document is listed apart', () => {
	const view = dedupeView(SMALL, 0.97);
	assert.deepEqual(
		view.groups.map((g) => [g.id, g.objectIds, g.points, g.chunkGroups]),
		[
			[0, ['oa', 'ob'], [0, 1, 2, 3], 2],
			[1, ['oc', 'od'], [4, 5], 1],
		],
		'the handbook pair is ONE group although two of its chunks pair up'
	);
	assert.deepEqual(view.groups[0]!.shared, { oa: 2, ob: 2 });
	assert.equal(view.groups[0]!.simMin, 0.981);
	assert.equal(view.groups[0]!.simMax, 0.995);
	assert.deepEqual(
		view.groups[0]!.pairs.map((p) => [p.a, p.b]),
		[
			[0, 2],
			[1, 3],
		]
	);
	assert.deepEqual(
		view.repeated.map((g) => [g.id, g.objectIds, g.points, g.sameDocument]),
		[[2, ['oe'], [6, 7], true]]
	);
	assert.ok(view.groups.every((g) => !g.sameDocument));
	assert.equal(view.pairs.length, 4);
	assert.deepEqual([...duplicateGroupOf(SMALL, 0.97)], [0, 0, 0, 0, 1, 1, 2, 2], 'the Points table numbers each point by its queue group');
});

test('removed documents leave the queue: their pairs are dropped before grouping', () => {
	const view = dedupeView(SMALL, 0.97, ['ob']);
	assert.deepEqual(
		view.groups.map((g) => g.objectIds),
		[['oc', 'od']]
	);
	assert.ok(
		view.pairs.every((p) => ![2, 3].includes(p.a) && ![2, 3].includes(p.b)),
		'no pair keeps a point of the removed document'
	);
});

test('the demo sample: three groups of different documents, none inside one document', () => {
	const demo = loadSample('sample_demo_1000.json');
	const view = dedupeView(demo, THRESHOLD_DEFAULT);
	assert.equal(view.groups.length, 3);
	assert.deepEqual(
		view.groups.map((g) => g.objectIds.length),
		[4, 2, 2]
	);
	assert.equal(view.repeated.length, 0);
	assert.equal(
		view.groups.reduce((sum, g) => sum + g.pairs.length, 0),
		8
	);
});

// =============================================================================
// KEEP POLICIES
// =============================================================================

const ROWS_INFO = [row('oa', 'C:/demo/handbooks/falcon_handbook.md', 3, '2026-10-02T09:00:00Z', 4000), row('ob', 'C:/demo/handbooks/falcon_handbook_rev2.md', 5, '2026-10-01T09:00:00Z', 5000), row('oc', 'C:/demo/field/kestrel_field_guide.md', 2, null), row('od', 'C:/demo/archive/kestrel_field_guide_copy.md', 2, null)];

test("docInfo joins the directory rows over the sample's documents (rows win; the sample fills paths and chunk counts)", () => {
	const info = docInfo(SMALL, ROWS_INFO);
	assert.deepEqual(info.get('ob'), { objectId: 'ob', path: 'C:/demo/handbooks/falcon_handbook_rev2.md', chunks: 5, ingestedAt: '2026-10-01T09:00:00Z', size: 5000, inSample: 2 });
	assert.deepEqual(info.get('oe'), { objectId: 'oe', path: 'C:/demo/ops/memo_q1.txt', chunks: 4, ingestedAt: null, size: null, inSample: 2 });
	assert.equal(docInfo(SMALL, null).get('oa')?.ingestedAt, null);
});

test('policies: oldest ingest, shortest path, most chunks; ties by objectId; unknown values last; nothing known → no choice', () => {
	const info = docInfo(SMALL, ROWS_INFO);
	const [handbooks, kestrels] = dedupeView(SMALL, 0.97).groups;
	assert.deepEqual(KEEP_POLICIES, ['oldest', 'shortest-path', 'most-chunks', 'manual']);
	assert.equal(applyPolicy(handbooks!, 'oldest', info), 'ob');
	assert.equal(applyPolicy(handbooks!, 'shortest-path', info), 'oa', "'shortest path' keeps falcon_handbook.md");
	assert.equal(applyPolicy(handbooks!, 'most-chunks', info), 'ob');
	assert.equal(applyPolicy(handbooks!, 'manual', info), null);
	assert.equal(applyPolicy(kestrels!, 'shortest-path', info), 'oc', 'field/kestrel_field_guide.md is shorter than the archive copy');
	assert.equal(applyPolicy(kestrels!, 'most-chunks', info), 'oc', 'a tie keeps the lower objectId');
	assert.equal(applyPolicy(kestrels!, 'oldest', info), null, 'no ingest time known in the group: no choice');
	const partly = docInfo(SMALL, [row('oc', 'C:/demo/field/kestrel_field_guide.md', 2, null), row('od', 'C:/demo/archive/kestrel_field_guide_copy.md', 2, '2026-10-05T00:00:00Z')]);
	assert.equal(applyPolicy(kestrels!, 'oldest', partly), 'od', 'a known time beats an unknown one');
	const tied = docInfo(SMALL, [row('oc', 'x/aa.md', 2, '2026-10-05T00:00:00Z'), row('od', 'x/bb.md', 2, '2026-10-05T00:00:00Z')]);
	assert.equal(applyPolicy(kestrels!, 'oldest', tied), 'oc');
	assert.equal(applyPolicy(kestrels!, 'shortest-path', tied), 'oc');
});

// =============================================================================
// THE QUEUE
// =============================================================================

test('the queue: a policy keeps one document per group and queues the others; a hand-picked keep wins; same-document groups never queue', () => {
	const info = docInfo(SMALL, ROWS_INFO);
	const view = dedupeView(SMALL, 0.97);
	let state = queueInit();
	assert.deepEqual(state, { threshold: THRESHOLD_DEFAULT, policy: 'manual', overrides: {} });
	assert.deepEqual(queued(view.groups, state, info, new Set()).objectIds, [], 'nothing is queued until a keep is chosen');
	state = queueReducer(state, { type: 'policy', value: 'shortest-path' });
	const q = queued(view.groups, state, info, new Set());
	assert.deepEqual(q.objectIds, ['ob', 'od']);
	assert.deepEqual(q.byGroup.get(view.groups[0]!.key), ['ob']);
	state = queueReducer(state, { type: 'keep', group: view.groups[0]!.key, objectId: 'ob' });
	assert.equal(keepOf(view.groups[0]!, state, info), 'ob');
	assert.deepEqual(queued(view.groups, state, info, new Set()).objectIds, ['oa', 'od']);
	state = queueReducer(state, { type: 'policy', value: 'most-chunks' });
	assert.deepEqual(state.overrides, {}, 'a new policy replaces the hand-picked keeps');
	assert.deepEqual(queued(view.groups, state, info, new Set()).objectIds, ['oa', 'od']);
	assert.equal(queueReducer(state, { type: 'keep', group: 'nope', objectId: 'oa' }).overrides.nope, 'oa');
	assert.ok(!queued([...view.groups, ...view.repeated], { ...state, policy: 'shortest-path' }, info, new Set()).objectIds.includes('oe'), 'a group inside one document never queues its document');
});

test('reviewed groups and documents removed already are not queued; a document another group keeps is never queued', () => {
	const info = docInfo(SMALL, ROWS_INFO);
	const view = dedupeView(SMALL, 0.97);
	const state = queueReducer(queueInit(), { type: 'policy', value: 'shortest-path' });
	assert.deepEqual(queued(view.groups, state, info, new Set(['oa', 'ob'])).objectIds, ['od'], 'a group whose documents are all reviewed is out of the queue');
	assert.deepEqual(queued(view.groups, state, info, new Set(['oa'])).objectIds, ['ob', 'od'], 'one reviewed document does not take its group out');
	// Two groups over a shared document: {oa, ob} keeps oa, {oa, oc} would queue oa under a hand-picked keep of oc.
	const shared = sampleOf(
		DOCS.slice(0, 3),
		[
			{ doc: 0, chunk: 0 },
			{ doc: 1, chunk: 0 },
			{ doc: 0, chunk: 1 },
			{ doc: 2, chunk: 0 },
		],
		[[[1, 0.99]], [[0, 0.99]], [[3, 0.98]], [[2, 0.98]]]
	);
	const two = dedupeView(shared, 0.97);
	assert.equal(two.groups.length, 2);
	const picked = queueReducer(queueReducer(queueInit(), { type: 'keep', group: two.groups[0]!.key, objectId: 'oa' }), { type: 'keep', group: two.groups[1]!.key, objectId: 'oc' });
	const q = queued(two.groups, picked, docInfo(shared, null), new Set());
	assert.deepEqual(q.objectIds, ['ob'], 'oa is kept by the first group, so the second does not queue it');
	assert.deepEqual(q.conflicts, ['oa']);
});

test('the threshold moves within 0.90 to 0.995 and re-groups at once from the sample alone', () => {
	let state = queueInit();
	state = queueReducer(state, { type: 'threshold', value: 0.5 });
	assert.equal(state.threshold, THRESHOLD_MIN);
	state = queueReducer(state, { type: 'threshold', value: 1 });
	assert.equal(state.threshold, THRESHOLD_MAX);
	assert.equal(dedupeView(SMALL, 0.985).groups.length, 1);
	assert.equal(dedupeView(SMALL, 0.97).groups.length, 2);
});

test('the slider issues no call: the queue and its panel import no call module and hold no channel', () => {
	const SRC = path.resolve(__dirname, '..', 'src');
	for (const file of ['map/dedupe.ts', 'components/DuplicatesPanel.tsx']) {
		const text = fs.readFileSync(path.join(SRC, file), 'utf8');
		assert.doesNotMatch(text, /from '\.\.?\/(map\/)?calls'|from '\.\.\/chat\/toolCalls'|\.invoke\(|callTool\(/, `${file} reaches the store`);
		assert.doesNotMatch(text, /\bchannel\b/, `${file} holds a channel`);
	}
});

// =============================================================================
// REVIEWED DOCUMENTS (per connection, in memory)
// =============================================================================

test("reviewed documents: per connection in the 'reviewed documents' cache, cleared through the registry", () => {
	markReviewed(reviewedDocuments, 'conn-a', ['oa', 'ob']);
	markReviewed(reviewedDocuments, 'conn-b', ['oc']);
	assert.deepEqual([...reviewedOf(reviewedDocuments, 'conn-a')].sort(), ['oa', 'ob']);
	assert.deepEqual([...reviewedOf(reviewedDocuments, 'conn-b')], ['oc'], 'another connection has its own set');
	unmarkReviewed(reviewedDocuments, 'conn-a', ['oa']);
	assert.deepEqual([...reviewedOf(reviewedDocuments, 'conn-a')], ['ob']);
	assert.deepEqual([...reviewedOf(reviewedDocuments, 'unknown')], []);
	assert.equal(reviewedOf(reviewedDocuments, 'unknown'), reviewedOf(reviewedDocuments, 'other'), 'one stable empty set, so a memoised queue does not recompute on every render');
	assert.ok(connectionCaches.names().includes('reviewed documents'));
	connectionCaches.clearAll();
	assert.equal(reviewedDocuments.size, 0);
	assert.deepEqual([...reviewedOf(reviewedDocuments, 'conn-a')], []);
});

// =============================================================================
// BUDGETS
// =============================================================================

test('budget: pairs over 30,000 kNN entries and the groups of a 2,000-point sample stay within a few milliseconds', () => {
	const n = 2000;
	const k = 15;
	const rows: Array<Array<[number, number]>> = [];
	for (let i = 0; i < n; i += 1) rows.push(Array.from({ length: k }, (_, r) => [(i + r + 1) % n, r === 0 && i % 10 === 0 ? 0.99 : 0.5 - r * 0.01] as [number, number]));
	const big = sampleOf(
		[['o', 'p', null]],
		Array.from({ length: n }, (_, c) => ({ doc: 0, chunk: c })),
		rows
	);
	let best = Infinity;
	for (let run = 0; run < 5; run += 1) {
		const started = performance.now();
		groups(pairsAt(big, 0.97));
		best = Math.min(best, performance.now() - started);
	}
	assert.ok(best < 15, `pairs and groups took ${best.toFixed(2)} ms`);
});
