// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP WIRING: rules pinned by reading the source (no React DOM harness)
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const SRC = path.resolve(__dirname, '..', 'src');
const strip = (text: string): string => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const read = (rel: string): string => strip(fs.readFileSync(path.join(SRC, rel), 'utf8'));
const MAP_COMPONENTS = ['MapToolbar', 'PointCanvas', 'PointInspector', 'NeighbourList', 'DuplicatesPanel', 'OutliersPanel', 'PointsTable', 'Legend', 'HeatStrip'];
const files = [...fs.readdirSync(path.join(SRC, 'map')).map((f) => `map/${f}`), ...MAP_COMPONENTS.map((n) => `components/${n}.tsx`), 'views/MapView.tsx'];

test('no map file stops event propagation or listens for keys above the map (shell drawers and dialogs keep their keys)', () => {
	for (const file of files) {
		const text = read(file);
		assert.doesNotMatch(text, /stopPropagation|stopImmediatePropagation/, `${file} stops propagation`);
		assert.doesNotMatch(text, /(window|document)\.addEventListener\(\s*'key/, `${file} listens for keys on ${'window/document'}`);
		assert.doesNotMatch(text, /from 'three'|from 'react-window'|crypto\.subtle/, `${file} uses a dependency the app may not`);
	}
});

test('the canvas observes its size, follows devicePixelRatio, redraws when revealed, and exposes data-points', () => {
	const canvas = read('components/PointCanvas.tsx');
	assert.match(canvas, /new ResizeObserver\(/);
	assert.match(canvas, /devicePixelRatio/);
	assert.match(canvas, /data-points=\{visibleCount\}/);
	assert.match(canvas, /role="application"/);
	assert.match(canvas, /tabIndex=\{0\}/);
	assert.match(canvas, /addEventListener\('wheel', onWheel, \{ passive: false \}\)/);
	assert.match(canvas, /props\.visible !== false/);
	assert.match(canvas, /createWebglRenderer\(canvas, \(\) => requestDraw\(\)\) \?\? createCanvas2dRenderer\(canvas\)/);
	const gl = read('map/renderer.webgl.ts');
	assert.match(gl, /ALIASED_POINT_SIZE_RANGE/);
	assert.match(gl, /'webglcontextlost'/);
	assert.match(gl, /'webglcontextrestored'/);
});

test('the view re-reads the theme tokens when the shell switches theme, and honours reduced motion (Safari 13 listeners too)', () => {
	const view = read('views/MapView.tsx');
	assert.match(view, /new MutationObserver\(/);
	assert.match(view, /getComputedStyle\(document\.documentElement\)/);
	assert.match(view, /prefers-reduced-motion: reduce/);
	assert.match(view, /addListener\(/);
});

test('the view samples on first open with the node\'s default size, sends neighbour calls through the newest-wins queue, and lays out in the worker', () => {
	const view = read('views/MapView.tsx');
	assert.match(view, /limits\.sample_default/);
	assert.match(view, /createLatestQueue/);
	assert.match(view, /createLayoutClient\(\{ createWorker: spawnLayoutWorker \}\)/);
	assert.match(view, /overlap < [\w.]*pcaOverlap/, 'the neighbour layout is kept only when it is at least as good as PCA');
	assert.match(view, /forgetCameras\(\)/, 'a reset to no connection forgets the cameras');
	assert.match(view, /data-knn-overlap=/);
	assert.match(view, /data-pca-overlap=/);
});

test('the browser lanes can read the map\'s state: tooltip, query, rays, layout, points', () => {
	const view = read('views/MapView.tsx');
	assert.match(view, /data-query-state=/);
	assert.match(view, /data-rays=\{rays\.length\}/);
	assert.match(view, /data-layout-state=\{layoutState\}/);
	assert.match(read('components/PointCanvas.tsx'), /data-map-tooltip/);
});

test('light samples are dithered within their 2-decimal rounding on PCA, so no lattice is drawn', () => {
	assert.match(read('views/MapView.tsx'), /sample\.mode === 'light' \? ditherRounded\(pca, 0\.01, /);
});

test('the Selection tab is wired to the console unchanged: every selected document goes to requestRemove (no cap here)', () => {
	const view = read('views/MapView.tsx');
	assert.match(view, /<SelectionTab[\s\S]*?onRemove=\{\(ids\) => actions\.requestRemove\(ids\)\}/);
	assert.doesNotMatch(view, /requestRemove\([^)]*\.slice\(|\.slice\(0, limits\.write_ids_max\)/, 'the map never truncates a removal to write_ids_max');
});

test('the view gives the canvas the layout shown, the lasso count and the overlaps, so its root carries the lanes\' attribute table', () => {
	const view = read('views/MapView.tsx');
	assert.match(view, /<PointCanvas[\s\S]*?layout=\{layout\}[\s\S]*?selectionCount=\{lassoKeys\.length > 0 \? lassoKeys\.length : null\}[\s\S]*?overlap=\{quality \? \{ layout: quality\.overlap, pca: quality\.pcaOverlap \} : null\}/);
	assert.match(view, /setLayoutState\('running'\);[\s\S]{0,200}setQuality\(null\)/, 'a new run clears the previous overlaps');
	const canvas = read('components/PointCanvas.tsx');
	// Written by each frame from what it drew; React never renders them (it would overwrite the frame's values).
	assert.match(canvas, /Object\.assign\(el\.dataset, overlayDataset\(drawn\)\)/);
	assert.match(canvas, /el\.dataset\.drawCount = /);
	assert.match(canvas, /el\.dataset\.camera = cameraSignature\(camera\)/);
	assert.doesNotMatch(canvas, /data-(star|rays|links|chunk-path|draw-count|camera)=\{/);
	// The hover box is a tooltip for the lanes and assistive tech, and keeps the perf lane's attribute.
	assert.match(canvas, /<div role="tooltip" data-map-tooltip=\{tooltip\.index\}/);
});

test('the Lasso toggle stays pressed after a selection (the next outline selects again); Lasso, L or Escape turn it off', () => {
	const view = read('views/MapView.tsx');
	const onLasso = /const onLasso = useCallback\(([\s\S]*?)\n\t\t\[sample/.exec(view);
	assert.ok(onLasso, 'onLasso found');
	assert.doesNotMatch(onLasso[1] as string, /setLasso\(/, 'a finished lasso leaves the toggle as the user set it');
	assert.match(view, /onToggleLasso=\{\(\) => setLasso\(\(on\) => !on\)\}/);
	assert.match(view, /action === 'lasso'\) setLasso\(\(on\) => !on\)/);
});
