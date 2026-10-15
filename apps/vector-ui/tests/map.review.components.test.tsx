// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// REVIEW PANELS: what the duplicates queue and the outlier review show and hand on
// =============================================================================
//
// Statically rendered (no effects run): what a person and a screen reader
// are told in each state. The panels' bodies are plain functions of their
// state, so the tests also call them directly and press their buttons to see
// what each one hands to the host (no DOM harness).
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DuplicatesBody, DuplicatesPanel, requestRemoval } from '../src/components/DuplicatesPanel';
import { OutliersBody, OutliersPanel } from '../src/components/OutliersPanel';
import type { Availability, IDocumentItem, IDocumentRowsSource, IKnnBlock, ISampleModel, ISampleResult } from '../src/contract/types';
import { dedupeView, docInfo, queueInit, queueReducer, queued } from '../src/map/dedupe';
import { outlierRows } from '../src/map/outliers';
import { loadSample, modelOf } from './support/map.samples';

const noop = (): void => undefined;
const on: Availability = { enabled: true, reason: null };
const off: Availability = { enabled: false, reason: 'Removing documents is turned off on this store node (allow_writes).' };
const html = (el: React.ReactElement): string => renderToStaticMarkup(el);
const demo = modelOf(loadSample('sample_demo_1000.json'));

/** Elements of a rendered tree (plain JSX only; the bodies call no component with hooks). */
function elements(node: unknown, out: React.ReactElement[] = []): React.ReactElement[] {
	if (Array.isArray(node)) node.forEach((child) => elements(child, out));
	else if (React.isValidElement(node)) {
		out.push(node);
		elements((node.props as { children?: unknown }).children, out);
	}
	return out;
}

/** The text of an element's children. */
function textOf(node: unknown): string {
	if (node === null || node === undefined || typeof node === 'boolean') return '';
	if (typeof node === 'string' || typeof node === 'number') return String(node);
	if (Array.isArray(node)) return node.map(textOf).join('');
	if (React.isValidElement(node)) return textOf((node.props as { children?: unknown }).children);
	return '';
}

/** The button whose text starts with `label`. */
function button(tree: React.ReactElement, label: string): React.ReactElement<{ onClick(): void; disabled?: boolean; title?: string }> {
	const found = elements(tree).find((el) => el.type === 'button' && textOf(el).trim().startsWith(label));
	assert.ok(found, `a "${label}" button`);
	return found as React.ReactElement<{ onClick(): void; disabled?: boolean; title?: string }>;
}

// A two-document handbook copy, a kestrel copy and a paragraph repeated inside one memo.
function small(): ISampleResult {
	const docs: Array<[string, string, number]> = [
		['oa', 'C:/demo/handbooks/falcon_handbook.md', 3],
		['ob', 'C:/demo/handbooks/falcon_handbook_rev2.md', 3],
		['oc', 'C:/demo/field/kestrel_field_guide.md', 2],
		['od', 'C:/demo/archive/kestrel_field_guide_copy.md', 2],
		['oe', 'C:/demo/ops/memo_q1.txt', 4],
	];
	const points = [0, 0, 1, 1, 2, 3, 4, 4].map((doc, i) => ({ doc, chunk: [0, 1, 0, 1, 0, 0, 0, 2][i] as number }));
	const rows: Array<Array<[number, number]>> = [[[2, 0.993]], [[3, 0.981]], [[0, 0.993]], [[1, 0.981]], [[5, 0.975]], [[4, 0.975]], [[7, 0.99]], [[6, 0.99]]];
	const knn: IKnnBlock = { k: 1, offsets_row: [0], cols: [], sims: [] };
	for (const r of rows) {
		for (const [j, s] of r) {
			knn.cols.push(j);
			knn.sims.push(s);
		}
		knn.offsets_row.push(knn.cols.length);
	}
	const base = loadSample('sample_demo_1000.json');
	return {
		...base,
		n: 8,
		n_requested: 8,
		docs: docs.map(([objectId, path, chunks], i) => ({ i, objectId, path, chunks, in_sample: points.filter((p) => p.doc === i).length })),
		points: { doc: points.map((p) => p.doc), chunk: points.map((p) => p.chunk), x: points.map(() => 0), y: points.map(() => 0), len: points.map(() => 90), snip: points.map(() => 'text'), pinned: points.map(() => 0) },
		knn,
		density: points.map(() => 0.5),
		outliers: [],
		duplicates: [],
	};
}
const SMALL = modelOf(small());

/** Directory rows for the small sample. */
const ROWS: IDocumentItem[] = [
	{ objectId: 'oa', path: 'C:/demo/handbooks/falcon_handbook.md', chunks: 3, has_first_chunk: true, tables: 0, deleted: false, nodeId: null, size: 4096, modifyTime: null, ingestedAt: '2026-10-02T09:00:00Z', pointId: null },
	{ objectId: 'ob', path: 'C:/demo/handbooks/falcon_handbook_rev2.md', chunks: 5, has_first_chunk: true, tables: 0, deleted: false, nodeId: null, size: 5120, modifyTime: null, ingestedAt: '2026-10-01T09:00:00Z', pointId: null },
];
const rowsSource: IDocumentRowsSource = { getRows: () => ROWS, subscribe: () => noop };

// =============================================================================
// DUPLICATES QUEUE
// =============================================================================

test('the queue: one fieldset per group with its documents, Keep radios labelled by path, its pairs and its similarity range', () => {
	const out = html(<DuplicatesPanel sample={demo} writes={on} onSelect={noop} onRemoveDocument={noop} />);
	assert.equal((out.match(/<fieldset/g) ?? []).length, 3);
	assert.match(out, /Group 1 · 4 documents · similarity 0\.9991–0\.9992/);
	assert.match(out, /Group 2 · 2 documents · similarity 0\.9998/);
	assert.equal((out.match(/type="radio"/g) ?? []).length, 8);
	assert.match(out, /aria-label="Keep C:\/demo\/field\/field_008\.md"/);
	assert.equal((out.match(/<li/g) ?? []).length, demo.result.duplicates.length, 'one row per pair');
	assert.match(out, /type="range"[^>]*aria-valuetext="similarity 0\.97"/);
	assert.match(out, /min="0\.9"[^>]*max="0\.995"|max="0\.995"[^>]*min="0\.9"/);
	assert.match(out, /Pairs among each point&#x27;s 15 nearest neighbours in this sample/);
	assert.match(out, /Within this sample of 1,000 chunks; draw a larger or light sample to cover more\./);
	assert.match(out, /role="status"[^>]*>No document queued/);
	assert.match(out, /<button[^>]*disabled=""[^>]*>Remove all queued \(0 documents\)<\/button>/);
	assert.match(out, /Keep oldest ingest/);
	assert.match(out, /Keep shortest path/);
	assert.match(out, /Keep most chunks/);
	assert.match(out, /Choose manually/);
});

test('a policy fills every group: the kept document is checked, the others are tagged queued, and the count is spoken', () => {
	const out = html(<DuplicatesPanel sample={SMALL} writes={on} documents={rowsSource} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ policy: 'shortest-path' }} />);
	assert.match(out, /role="status"[^>]*>2 documents queued/);
	assert.match(out, /<button[^>]*>Remove all queued \(2 documents\)<\/button>/);
	assert.match(out, /checked=""[^>]*aria-label="Keep C:\/demo\/handbooks\/falcon_handbook\.md"|aria-label="Keep C:\/demo\/handbooks\/falcon_handbook\.md"[^>]*checked=""/);
	assert.equal((out.match(/>queued</g) ?? []).length, 2);
	assert.match(out, /3 chunks · ingested 2026-10-02 · 4 KB · 2 of 2 sampled chunks match/);
	assert.match(out, /Repeated text inside one document/);
	assert.match(out, /C:\/demo\/ops\/memo_q1\.txt/);
});

test('writes off: Keep radios and every Remove disabled, and the reason shown as text', () => {
	const out = html(<DuplicatesPanel sample={SMALL} writes={off} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ policy: 'shortest-path' }} />);
	assert.equal((out.match(/type="radio"/g) ?? []).length, 4);
	assert.equal((out.match(/type="radio"[^>]*disabled=""|disabled=""[^>]*type="radio"/g) ?? []).length, 4);
	assert.match(out, /<button[^>]*disabled=""[^>]*>Remove all queued \(2 documents\)<\/button>/);
	assert.match(out, /<button[^>]*disabled=""[^>]*>Remove the other<\/button>/);
	assert.ok(out.includes(off.reason as string));
});

test('no pair at the threshold: the sentence names the threshold', () => {
	const none = modelOf({ ...SMALL.result, knn: { k: 0, offsets_row: SMALL.result.knn.offsets_row.map(() => 0), cols: [], sims: [] } });
	assert.match(html(<DuplicatesPanel sample={none} writes={on} onSelect={noop} onRemoveDocument={noop} />), /No near-duplicate pairs at similarity 0\.97 or above in this sample\./);
	assert.match(html(<DuplicatesPanel sample={SMALL} writes={on} onSelect={noop} onRemoveDocument={noop} initial={{ threshold: 0.995 }} />), /No near-duplicate pairs at similarity 0\.995 or above/);
});

test('a group inside one document offers Show and Open, never a Remove or a Keep', () => {
	const sample = small();
	const view = dedupeView(sample, 0.97);
	const tree = DuplicatesBody({ sample: modelOf(sample), writes: on, view, info: docInfo(sample, null), state: queueInit(), reviewed: new Set(), queue: queued(view.groups, queueInit(), docInfo(sample, null), new Set()), done: null, bulk: true, onThreshold: noop, onPolicy: noop, onKeep: noop, onShow: noop, onReview: noop, onRemove: noop, onOpenDocument: noop });
	const repeated = elements(tree).find((el) => (el.props as { 'data-repeated'?: string })['data-repeated'] !== undefined);
	assert.ok(repeated, 'the repeated-text section');
	const inside = elements(repeated);
	assert.ok(inside.some((el) => el.type === 'button' && textOf(el) === 'Open'));
	assert.ok(!inside.some((el) => el.type === 'button' && /Remove/.test(textOf(el))));
	assert.ok(!inside.some((el) => el.type === 'input'));
});

test("buttons hand the host what they say: Show the group's points, Mark reviewed its documents, Remove the others and Remove all queued their objectIds", () => {
	const sample = small();
	const info = docInfo(sample, ROWS);
	const view = dedupeView(sample, 0.97);
	const state = queueReducer(queueInit(), { type: 'policy', value: 'shortest-path' });
	const shown: number[][] = [];
	const reviewed: Array<[string[], boolean]> = [];
	const removed: string[][] = [];
	const tree = DuplicatesBody({ sample: modelOf(sample), writes: on, view, info, state, reviewed: new Set(), queue: queued(view.groups, state, info, new Set()), done: null, bulk: true, onThreshold: noop, onPolicy: noop, onKeep: noop, onShow: (points) => shown.push([...points]), onReview: (group, value) => reviewed.push([[...group.objectIds], value]), onRemove: (ids) => removed.push([...ids]) });
	button(tree, 'Show group').props.onClick();
	button(tree, 'Mark reviewed').props.onClick();
	button(tree, 'Remove the other').props.onClick();
	button(tree, 'Remove all queued').props.onClick();
	assert.deepEqual(shown, [[0, 1, 2, 3]]);
	assert.deepEqual(reviewed, [[['oa', 'ob'], true]]);
	assert.deepEqual(removed, [['ob'], ['ob', 'od']]);
});

test('reviewed groups leave the queue and can be reviewed again; the done line counts what the console removed', () => {
	const sample = small();
	const info = docInfo(sample, ROWS);
	const view = dedupeView(sample, 0.97);
	const state = queueReducer(queueInit(), { type: 'policy', value: 'shortest-path' });
	const done = new Set(['oa', 'ob']);
	const tree = DuplicatesBody({ sample: modelOf(sample), writes: on, view, info, state, reviewed: done, queue: queued(view.groups, state, info, done), done: 'Removed 1 document (5 chunks)', bulk: true, onThreshold: noop, onPolicy: noop, onKeep: noop, onShow: noop, onReview: noop, onRemove: noop });
	const out = renderToStaticMarkup(tree);
	assert.match(out, /Reviewed \(1 group\)/);
	assert.match(out, /Review again/);
	assert.match(out, /1 document queued/);
	assert.match(out, /Removed 1 document \(5 chunks\)/);
});

test('requestRemoval: one document through the single dialog when that is all the host has, several only through the batched one', () => {
	const single: string[] = [];
	const many: string[][] = [];
	assert.equal(requestRemoval(['ob'], { onRemoveDocument: (id) => single.push(id) }), true);
	assert.deepEqual(single, ['ob']);
	assert.equal(requestRemoval(['ob', 'od'], { onRemoveDocument: (id) => single.push(id) }), false, 'never one dialog per document');
	assert.deepEqual(single, ['ob']);
	assert.equal(requestRemoval(['ob', 'od'], { onRemoveDocument: (id) => single.push(id), onRemoveDocuments: (ids) => many.push([...ids]) }), true);
	assert.equal(requestRemoval(['ob'], { onRemoveDocument: (id) => single.push(id), onRemoveDocuments: (ids) => many.push([...ids]) }), true);
	assert.deepEqual(many, [['ob', 'od'], ['ob']]);
	assert.equal(requestRemoval([], { onRemoveDocument: noop }), false);
});

test('without the batched remove, the bulk button is disabled with its reason', () => {
	const out = html(<DuplicatesPanel sample={SMALL} writes={on} onSelect={noop} onRemoveDocument={noop} initial={{ policy: 'shortest-path' }} />);
	assert.match(out, /<button[^>]*disabled=""[^>]*title="This view cannot remove several documents at once\."[^>]*>Remove all queued \(2 documents\)<\/button>/);
});

test("the sample model's removed documents leave the groups", () => {
	const sample: ISampleModel = { ...SMALL, removed: ['ob'] };
	const out = html(<DuplicatesPanel sample={sample} writes={on} onSelect={noop} onRemoveDocument={noop} />);
	assert.doesNotMatch(out, /falcon_handbook_rev2/);
	assert.equal((out.match(/<fieldset/g) ?? []).length, 2, 'the kestrel pair and the repeated memo');
});

test('after the console removed queued documents the panel says how many, with the chunks the store reported per document', () => {
	const sample: ISampleModel = { ...SMALL, removed: ['ob'] };
	const out = html(<DuplicatesPanel sample={sample} writes={on} documents={rowsSource} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ requested: ['ob', 'od'] }} />);
	assert.match(out, /Removed 1 of 2 documents \(5 chunks\); 1 is still stored\./);
	const all: ISampleModel = { ...SMALL, removed: ['ob', 'od'] };
	assert.match(html(<DuplicatesPanel sample={all} writes={on} documents={rowsSource} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ requested: ['ob', 'od'] }} />), /Removed 2 documents \(7 chunks\)/);
});

test('the reviewed documents of a connection come from its cache, so the queue keeps them across tab switches', () => {
	const cache = new Map<string, ReadonlySet<string>>([['conn-r', new Set(['oa', 'ob'])]]);
	const out = html(<DuplicatesPanel sample={SMALL} writes={on} connectionKey="conn-r" reviewedCache={cache} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ policy: 'shortest-path' }} />);
	assert.match(out, /Reviewed \(1 group\)/);
	assert.match(out, /role="status"[^>]*>1 document queued/);
	assert.match(html(<DuplicatesPanel sample={SMALL} writes={on} connectionKey="conn-other" reviewedCache={cache} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} initial={{ policy: 'shortest-path' }} />), /2 documents queued/, 'another connection has its own set');
});

test('a group of shared passages says so; nothing is removable before a keep is chosen', () => {
	const out = html(<DuplicatesPanel sample={demo} writes={on} onSelect={noop} onRemoveDocument={noop} onRemoveDocuments={noop} />);
	assert.equal((out.match(/Shared passages only: each of these documents also has text the others do not\./g) ?? []).length, 3, 'one chunk of documents with many: passages, not copies');
	assert.doesNotMatch(html(<DuplicatesPanel sample={SMALL} writes={on} onSelect={noop} onRemoveDocument={noop} />), /Shared passages only/, 'a copy shares most of its chunks');
	assert.match(out, /<button[^>]*disabled=""[^>]*title="Choose the document to keep first"[^>]*>Remove the others<\/button>/);
});

// =============================================================================
// OUTLIER REVIEW
// =============================================================================

test('the outlier review: a percentile select, one row per outlier with why, and the count spoken', () => {
	const out = html(<OutliersPanel sample={demo} onSelect={noop} onShowNeighbours={noop} onRemoveDocument={noop} writes={on} />);
	assert.equal((out.match(/<li/g) ?? []).length, 10);
	assert.match(out, /Lowest density/);
	assert.match(out, /<option value="1" selected="">1 %<\/option><option value="2">2 %<\/option><option value="5">5 %<\/option>/);
	assert.match(out, /role="status"[^>]*>10 points: the lowest 1 % by density/);
	assert.match(out, /C:\/demo\/finance\/ocr_scan_junk\.txt #\d+/);
	assert.match(out, /density 0\.24 vs sample median 0\.68; nearest neighbour 0\.\d\d in /);
	assert.equal((out.match(/>Show neighbours</g) ?? []).length, 10);
	assert.equal((out.match(/>Mark reviewed</g) ?? []).length, 10);
	assert.equal((out.match(/<button[^>]*>Remove document<\/button>/g) ?? []).length, 10);
	assert.doesNotMatch(out, /<button[^>]*disabled=""[^>]*>Remove document<\/button>/);
});

test('a larger percentile lists more rows from the same sample', () => {
	assert.equal((html(<OutliersPanel sample={demo} onSelect={noop} initial={{ percentile: 5 }} />).match(/<li/g) ?? []).length, 50);
	assert.match(html(<OutliersPanel sample={demo} onSelect={noop} initial={{ percentile: 2 }} />), /20 points: the lowest 2 % by density/);
});

test('Remove document is disabled with the reason when writes are off, and absent without a remove handler', () => {
	const out = html(<OutliersPanel sample={demo} onSelect={noop} onRemoveDocument={noop} writes={off} />);
	assert.equal((out.match(/<button[^>]*disabled=""[^>]*>Remove document<\/button>/g) ?? []).length, 10);
	assert.ok(out.includes(off.reason as string));
	assert.equal((html(<OutliersPanel sample={demo} onSelect={noop} onRemoveDocument={noop} />).match(/<button[^>]*disabled=""[^>]*>Remove document<\/button>/g) ?? []).length, 10, 'no writes given: closed');
	assert.doesNotMatch(html(<OutliersPanel sample={demo} onSelect={noop} />), /Remove document|Show neighbours/);
});

test('the outlier buttons hand the host the point or its document', () => {
	const rows = outlierRows(demo.result, 1);
	const picked: number[] = [];
	const neighbours: number[] = [];
	const reviewed: Array<[string, boolean]> = [];
	const removed: string[] = [];
	const tree = OutliersBody({ rows, percentile: 1, writes: on, canRemove: true, canShowNeighbours: true, onPercentile: noop, onSelect: (i) => picked.push(i), onReview: (id, value) => reviewed.push([id, value]), onRemove: (id) => removed.push(id), onShowNeighbours: (i) => neighbours.push(i) });
	button(tree, 'C:/demo/finance/ocr_scan_junk.txt').props.onClick();
	button(tree, 'Show neighbours').props.onClick();
	button(tree, 'Mark reviewed').props.onClick();
	button(tree, 'Remove document').props.onClick();
	assert.deepEqual(picked, [262]);
	assert.deepEqual(neighbours, [262]);
	assert.deepEqual(reviewed, [[rows[0]!.objectId, true]]);
	assert.deepEqual(removed, [rows[0]!.objectId]);
});

test("reviewed outliers are tagged and counted, from the connection's cache", () => {
	const ocr = demo.result.docs[demo.result.points.doc[262] as number]!.objectId;
	const cache = new Map<string, ReadonlySet<string>>([['conn-o', new Set([ocr])]]);
	const out = html(<OutliersPanel sample={demo} onSelect={noop} connectionKey="conn-o" reviewedCache={cache} />);
	const ocrRows = outlierRows(demo.result, 1).filter((r) => r.objectId === ocr).length;
	assert.equal((out.match(/>reviewed</g) ?? []).length, ocrRows);
	assert.equal((out.match(/>Review again</g) ?? []).length, ocrRows);
	assert.match(out, new RegExp(`10 points: the lowest 1 % by density · ${ocrRows} reviewed`));
});

test('no outliers: the sentence, and nothing to pick', () => {
	const none = modelOf({ ...demo.result, outliers: [] });
	const out = html(<OutliersPanel sample={none} onSelect={noop} />);
	assert.match(out, /No outliers in this sample\./);
	assert.doesNotMatch(out, /<select/);
});

test('an outlier of a removed document leaves the list', () => {
	const ocr = demo.result.docs[demo.result.points.doc[262] as number]!.objectId;
	const out = html(<OutliersPanel sample={{ ...demo, removed: [ocr] }} onSelect={noop} />);
	assert.doesNotMatch(out, /ocr_scan_junk/);
});
