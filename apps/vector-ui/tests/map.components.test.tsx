// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP COMPONENTS: static render of every panel (no DOM; react-dom/server)
// =============================================================================
//
// The panels are plain JSX over shell tokens, so they render in Node. These
// pin what a person (and a screen reader) is told; the canvas behaviour is
// covered by the pure modules and the browser lanes.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DuplicatesPanel } from '../src/components/DuplicatesPanel';
import { HeatStrip } from '../src/components/HeatStrip';
import { Legend } from '../src/components/Legend';
import { MapToolbar } from '../src/components/MapToolbar';
import { NeighbourList } from '../src/components/NeighbourList';
import { OutliersPanel } from '../src/components/OutliersPanel';
import { PointCanvas } from '../src/components/PointCanvas';
import { PointInspector } from '../src/components/PointInspector';
import { PointsTable } from '../src/components/PointsTable';
import { createSelectionStore } from '../src/contract/bridge';
import type { INeighborsResult, ISampleResult, IVectorLimits, VectorKey } from '../src/contract/types';
import { colourPoints } from '../src/map/colours';
import { readPalette } from '../src/map/tokens';
import { SelectionTab } from '../src/views/MapView';
import { loadSample, modelOf, pcaXY } from './support/map.samples';

const FIX = path.resolve(__dirname, 'fixtures', 'provisional');
const neighbours = JSON.parse(fs.readFileSync(path.join(FIX, 'neighbors_key.json'), 'utf8')) as INeighborsResult;
const limits = (JSON.parse(fs.readFileSync(path.join(FIX, 'dialect_pgvector.json'), 'utf8')) as { limits: IVectorLimits }).limits;
const demo = modelOf(loadSample('sample_demo_1000.json'));
const native = modelOf(loadSample('sample_native_knn.json'));
const palette = readPalette((t) => ({ '--rr-palette-mode': 'dark', '--rr-bg-default': '#161616', '--rr-bg-paper': '#242424' } as Record<string, string>)[t] ?? '');
const noop = (): void => undefined;
const html = (el: React.ReactElement): string => renderToStaticMarkup(el);

/** Elements of a rendered tree (function components are not called; plain JSX only). */
function elements(node: unknown, out: React.ReactElement[] = []): React.ReactElement[] {
	if (Array.isArray(node)) node.forEach((child) => elements(child, out));
	else if (React.isValidElement(node)) {
		out.push(node);
		elements((node.props as { children?: unknown }).children, out);
	}
	return out;
}

/** The button whose text is `label`. */
function button(tree: React.ReactElement, label: string): React.ReactElement<{ onClick(): void; disabled?: boolean }> {
	const found = elements(tree).find((el) => el.type === 'button' && elements((el.props as { children?: unknown }).children).length === 0 && String((el.props as { children?: unknown }).children).trim() === label);
	assert.ok(found, `a "${label}" button`);
	return found as React.ReactElement<{ onClick(): void; disabled?: boolean }>;
}

test('Legend: sample line, one row per colour, the point cap, who computed the neighbour graph, and the distance caveat', () => {
	const colouring = colourPoints(demo.result, 'document', palette);
	const out = html(<Legend sample={demo} colourBy="document" pointCap={2000} backend="pgvector" colouring={colouring} />);
	assert.match(out, /Showing 1,000 of 1,318 chunks \(random sample\)/);
	assert.equal((out.match(/<li/g) ?? []).length, colouring.legend.length);
	assert.match(out, /Other \(32 documents\)/);
	assert.match(out, /Detailed mode draws up to 2,000 points/);
	assert.match(out, /2D distance is approximate; ranks and scores are exact/);
	const qdrant = html(<Legend sample={native} colourBy="document" pointCap={2000} backend="qdrant" />);
	assert.match(qdrant, /neighbour graph computed by Qdrant/);
	assert.match(qdrant, /data-knn-source="native"/);
});

test('NeighbourList: one button per neighbour with path, chunk and similarity; below-floor rows are tagged', () => {
	const items = neighbours.items.map((item, i) => (i === 11 ? { ...item, below_floor: true } : item));
	const out = html(<NeighbourList items={items} onSelect={noop} />);
	assert.equal((out.match(/<button/g) ?? []).length, 12);
	assert.match(out, /aria-label="Nearest chunks in the collection"/);
	assert.match(out, /ops_005\.pdf/);
	assert.match(out, /0\.930/);
	assert.equal((out.match(/below floor/g) ?? []).length, 1);
});

test('PointInspector: a hint with nothing selected; the chunk, its neighbours and gated actions with one selected', () => {
	const writesOff = { enabled: false, reason: 'Removing documents is turned off on this store node (allow_writes).' };
	assert.match(html(<PointInspector sample={demo} index={null} neighbours={null} querySim={null} writes={writesOff} onOpenDocument={noop} onFindSimilar={noop} onRemoveDocument={noop} />), /Click a point or use the arrow keys/);
	const out = html(<PointInspector sample={demo} index={5} neighbours={neighbours} querySim={0.41} score={0.39} writes={writesOff} onOpenDocument={noop} onFindSimilar={noop} onRemoveDocument={noop} />);
	const doc = demo.result.docs[demo.result.points.doc[5] as number]!;
	assert.ok(out.includes(doc.path));
	assert.match(out, new RegExp(`Chunk ${demo.result.points.chunk[5]} of ${doc.chunks}`));
	assert.match(out, /Similarity to the query 0\.410/);
	assert.match(out, /pipeline score 0\.390/);
	assert.match(out, /12 nearest in the collection/);
	assert.match(out, /Open document/);
	assert.match(out, /Find similar/);
	assert.match(out, /<button[^>]*disabled=""[^>]*>Remove document<\/button>/);
	assert.ok(out.includes(writesOff.reason), 'the reason is shown as text, not only as a tooltip');
});

test('DuplicatesPanel and OutliersPanel list the node\'s findings, or say there are none', () => {
	const writes = { enabled: true, reason: null };
	const dup = html(<DuplicatesPanel sample={demo} writes={writes} onSelect={noop} onRemoveDocument={noop} />);
	assert.equal((dup.match(/<li/g) ?? []).length, demo.result.duplicates.length);
	assert.match(dup, /0\.9998/);
	const none = modelOf({ ...demo.result, duplicates: [], outliers: [] });
	assert.match(html(<DuplicatesPanel sample={none} writes={writes} onSelect={noop} onRemoveDocument={noop} />), /No near-duplicate pairs/);
	const out = html(<OutliersPanel sample={demo} onSelect={noop} />);
	assert.equal((out.match(/<li/g) ?? []).length, demo.result.outliers.length);
	assert.match(html(<OutliersPanel sample={none} onSelect={noop} />), /No outliers/);
});

test('PointsTable: the accessible alternative, one page of 100 rows with a caption and paging', () => {
	const out = html(<PointsTable sample={demo} querySims={null} selected={3} onSelect={noop} />);
	assert.match(out, /<caption[^>]*>Points of the sample/);
	assert.equal((out.match(/<tr/g) ?? []).length, 101, 'header plus 100 rows');
	assert.match(out, /Rows 1–100 of 1,000/);
	assert.match(out, /aria-selected="true"/);
	const sims = Array.from({ length: demo.result.n }, (_, i) => i / demo.result.n);
	assert.match(html(<PointsTable sample={demo} querySims={sims} selected={null} onSelect={noop} />), /Query similarity/);
});

test('HeatStrip: one cell per chunk with its similarity spoken, a single tab stop, and the focused chunk marked', () => {
	const out = html(<HeatStrip chunks={6} scores={[{ chunkId: 0, sim: 0.2 }, { chunkId: 3, sim: 0.8 }]} focused={3} onSelectChunk={noop} label="Similarity of each chunk to the query" />);
	assert.match(out, /aria-label="Similarity of each chunk to the query"/);
	assert.equal((out.match(/<button/g) ?? []).length, 6);
	assert.equal((out.match(/tabindex="0"/gi) ?? []).length, 1);
	assert.match(out, /aria-label="Chunk 3: similarity 0\.800"/);
	assert.match(out, /aria-label="Chunk 1: no similarity"/);
	assert.match(out, /aria-current="true"/);
});

test('MapToolbar: sizes capped by the node\'s limits, t-SNE disabled above 1,000 with its reason, query disabled with its reason, toggles pressed', () => {
	const base = { limits, sample: demo, busy: null, layout: 'pca' as const, colourBy: 'document' as const, lasso: true, table: false, onSample: noop, onLayout: noop, onCancel: noop, onColourBy: noop, onQuery: noop, onToggleLasso: noop, onFit: noop, onToggleTable: noop };
	const out = html(<MapToolbar {...base} query={{ enabled: false, reason: 'Text queries need the embedding node reachable from the Tools source' }} tsneReason="t-SNE is limited to 1,000 points." />);
	assert.match(out, /<option value="detailed:2000"/);
	assert.doesNotMatch(out, /detailed:3000/);
	assert.match(out, /<option value="light:5000"/);
	assert.match(out, /<option value="tsne" disabled=""/);
	assert.match(out, /Text queries need the embedding node reachable from the Tools source/);
	assert.match(out, /<button[^>]*disabled=""[^>]*>Run<\/button>/);
	// Each control is named explicitly: Chrome names a label-wrapped select by its selected option otherwise.
	for (const name of ['Points', 'Layout', 'Colour by', 'Query']) assert.match(out, new RegExp(`aria-label="${name}"`), `${name} is named`);
	assert.match(out, /aria-pressed="true"[^>]*>Lasso/);
	assert.match(out, /aria-pressed="false"[^>]*>Table/);
	const busy = html(<MapToolbar {...base} busy="Laying out…" canCancel query={{ enabled: true, reason: null }} />);
	assert.match(busy, /Laying out…/);
	assert.match(busy, />Cancel<\/button>/);
});

test('Selection tab: "Remove these documents" hands the console EVERY selected document (it confirms and batches), never a silent first 100', () => {
	// 260 points over 250 documents: more than write_ids_max (100).
	const keys: VectorKey[] = Array.from({ length: 260 }, (_, i) => [`doc-${i % 250}`, Math.floor(i / 250)] as VectorKey);
	const asked: Array<readonly string[]> = [];
	const props = { keys, chat: { enabled: true, reason: null }, writes: { enabled: true, reason: null }, onAskAbout: (ids: readonly string[]) => asked.push(ids), onRemove: (ids: readonly string[]) => asked.push(ids), onCopy: noop };
	assert.equal(limits.write_ids_max, 100);
	const tree = SelectionTab(props);
	assert.match(html(tree), /260 points selected from 250 documents\./);
	button(tree, 'Remove these documents').props.onClick();
	assert.equal(asked[0]?.length, 250, 'the console is asked about all 250 documents the tab names');
	assert.deepEqual([...(asked[0] ?? [])].sort(), Array.from({ length: 250 }, (_, i) => `doc-${i}`).sort());
	button(tree, 'Ask about these only').props.onClick();
	assert.equal(asked[1]?.length, 250);
	const off = SelectionTab({ ...props, writes: { enabled: false, reason: 'Removing documents is turned off on this store node (allow_writes).' } });
	assert.equal(button(off, 'Remove these documents').props.disabled, true);
	assert.match(html(off), /turned off on this store node/);
	assert.match(html(SelectionTab({ ...props, keys: [] })), /Turn on the lasso \(L\)/);
});

/** The PointCanvas root's opening tag, statically rendered (effects do not run: no canvas is needed). */
function canvasRoot(result: ISampleResult, extra: Partial<React.ComponentProps<typeof PointCanvas>> = {}): string {
	const props: React.ComponentProps<typeof PointCanvas> = { sample: modelOf(result), positions: pcaXY(result), dimensions: 2, colours: Array.from({ length: result.n }, () => '#888888'), selection: createSelectionStore(), lasso: false, onHover: noop, onPick: noop, onLasso: noop, ...extra };
	const out = html(<PointCanvas {...props} />);
	const tag = /<div[^>]*class="vector-map-canvas"[^>]*>/.exec(out);
	assert.ok(tag, 'the canvas root renders');
	return tag[0];
}

test('PointCanvas draws sample_demo_1000.json and the light 5,000 fixture with data-points equal to the points drawn (hidden ones left out)', () => {
	assert.match(canvasRoot(loadSample('sample_demo_1000.json')), /data-points="1000"/);
	assert.match(canvasRoot(loadSample('sample_light_5000.json')), /data-points="5000"/);
	const hidden = new Uint8Array(1000);
	hidden[3] = hidden[10] = hidden[999] = 1;
	assert.match(canvasRoot(loadSample('sample_demo_1000.json'), { hidden }), /data-points="997"/);
});

test('PointCanvas root carries the browser lanes\' attribute table: mode, layout, selected / focused / lasso count (empty for none), both kNN overlaps', () => {
	const demo1000 = loadSample('sample_demo_1000.json');
	const idle = canvasRoot(demo1000);
	for (const [attr, value] of [['data-mode', 'detailed'], ['data-layout', 'pca'], ['data-selected', ''], ['data-focused', ''], ['data-selection', ''], ['data-overlap-pca', ''], ['data-overlap-layout', '']]) {
		assert.ok(idle.includes(`${attr}="${value}"`), `${attr}="${value}" in ${idle}`);
	}
	const busy = canvasRoot(demo1000, { layout: 'neighbour-graph', overlay: { selected: 5, focused: 0 }, selectionCount: 42, overlap: { layout: 0.50234, pca: 0.16719 } });
	for (const [attr, value] of [['data-layout', 'neighbour-graph'], ['data-selected', '5'], ['data-focused', '0'], ['data-selection', '42'], ['data-overlap-layout', '0.5023'], ['data-overlap-pca', '0.1672']]) {
		assert.ok(busy.includes(`${attr}="${value}"`), `${attr}="${value}" in ${busy}`);
	}
	assert.match(canvasRoot(loadSample('sample_light_5000.json')), /data-mode="light"/);
});
