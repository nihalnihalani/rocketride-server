// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP RENDERERS: WebGL1 points, the Canvas2D fallback, and the overlay
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { viewMatrix } from '../src/map/camera';
import { drawOverlay, overlayDataset } from '../src/map/overlay';
import type { IOverlayModel } from '../src/map/overlay';
import { createCanvas2dRenderer } from '../src/map/renderer.canvas2d';
import { FLAG, FRAGMENT_SHADER, VERTEX_SHADER, createWebglRenderer, packPoints, sizeCanvas } from '../src/map/renderer.webgl';
import { FakeCanvas, fake2d, fakeGl } from './support/map.fakes';

const vp = { width: 400, height: 300 };
const matrix = viewMatrix({ mode: '2d', cx: 0, cy: 0, scale: 10 }, vp);

/** Three points: one plain, one outlined, one hidden. */
function three() {
	return packPoints({
		positions: new Float32Array([0, 0, 1, 1, -2, 3]),
		dims: 2,
		rgba: new Uint8Array([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255]),
		outlined: new Uint8Array([0, 1, 0]),
		hidden: new Uint8Array([0, 0, 1]),
		emphasised: null,
		hollow: null,
	});
}

test('points are packed as x,y,z per point with flag bits for outline, hidden, hollow and emphasis', () => {
	const data = three();
	assert.equal(data.count, 3);
	assert.deepEqual(Array.from(data.positions), [0, 0, 0, 1, 1, 0, -2, 3, 0]);
	assert.deepEqual(Array.from(data.flags), [0, FLAG.outlined, FLAG.hidden]);
	const more = packPoints({ positions: new Float32Array([0, 0, 1]), dims: 3, rgba: new Uint8Array(4), outlined: null, hidden: null, emphasised: new Uint8Array([1]), hollow: new Uint8Array([1]) });
	assert.equal(more.flags[0], FLAG.emphasised | FLAG.hollow);
	assert.deepEqual(Array.from(more.positions), [0, 0, 1]);
});

test('the shaders are WebGL1 (Safari 13): round sprites through gl_PointCoord, sizes clamped to the device range', () => {
	assert.doesNotMatch(VERTEX_SHADER + FRAGMENT_SHADER, /#version 300|\bin vec|\bout vec|texture\(/);
	assert.match(FRAGMENT_SHADER, /gl_PointCoord/);
	assert.match(FRAGMENT_SHADER, /discard/);
	assert.match(VERTEX_SHADER, /clamp\([^;]*u_minSize, u_maxSize\)/);
});

test('no WebGL: the factory answers null so the Canvas2D renderer takes over', () => {
	const canvas = new FakeCanvas({ webgl: null });
	assert.equal(createWebglRenderer(canvas as unknown as HTMLCanvasElement, () => undefined), null);
});

test('WebGL: reads the point-size range, uploads on setPoints only, draws every point in one POINTS call', () => {
	const fake = fakeGl([1, 32]);
	const canvas = new FakeCanvas({ webgl: fake.gl });
	const renderer = createWebglRenderer(canvas as unknown as HTMLCanvasElement, () => undefined);
	assert.ok(renderer);
	assert.equal(renderer.kind, 'webgl');
	assert.equal(renderer.pointSizeRange[1], 32);
	renderer.resize(400, 300, 2);
	renderer.setPoints(three(), [1, 1, 1]);
	const uploads = fake.count('bufferData');
	assert.equal(uploads, 3, 'positions, colours, flags');
	renderer.render({ matrix, pointSizePx: 6, dpr: 2 });
	renderer.render({ matrix, pointSizePx: 6, dpr: 2 });
	assert.equal(fake.count('bufferData'), uploads, 'drawing again uploads nothing');
	const draw = fake.last('drawArrays');
	assert.ok(draw);
	assert.equal(draw.args[0], (fake.gl as unknown as Record<string, number>).POINTS);
	assert.equal(draw.args[2], 3);
	assert.equal(canvas.width, 800);
	assert.equal(canvas.height, 600);
});

test('a lost WebGL context stops drawing (and is not let go); a restored one is rebuilt and redrawn', () => {
	const fake = fakeGl();
	const canvas = new FakeCanvas({ webgl: fake.gl });
	let redraws = 0;
	const renderer = createWebglRenderer(canvas as unknown as HTMLCanvasElement, () => (redraws += 1));
	assert.ok(renderer);
	renderer.setPoints(three(), [1, 1, 1]);
	const lost = canvas.dispatch('webglcontextlost');
	assert.equal(lost.prevented, true, 'preventDefault lets the browser restore it');
	assert.equal(renderer.lost, true);
	const before = fake.count('drawArrays');
	renderer.render({ matrix, pointSizePx: 6, dpr: 1 });
	assert.equal(fake.count('drawArrays'), before);
	const programs = fake.count('createProgram');
	canvas.dispatch('webglcontextrestored');
	assert.equal(renderer.lost, false);
	assert.equal(fake.count('createProgram'), programs + 1);
	assert.equal(redraws, 1);
	renderer.destroy();
	assert.equal(canvas.listeners.get('webglcontextlost')?.length, 0);
});

test('the canvas is never sized 0x0 (a hidden tab measures 0), and follows devicePixelRatio', () => {
	const canvas = new FakeCanvas({});
	sizeCanvas(canvas as unknown as HTMLCanvasElement, 0, 0, 2);
	assert.equal(canvas.width, 1);
	assert.equal(canvas.height, 1);
	sizeCanvas(canvas as unknown as HTMLCanvasElement, 320.4, 200, 1.5);
	assert.deepEqual([canvas.width, canvas.height], [481, 300]);
	assert.deepEqual([canvas.style.width, canvas.style.height], ['320.4px', '200px']);
});

test('Canvas2D fallback: one circle per visible point, outlines stroked, hidden points skipped', () => {
	const fake = fake2d();
	const canvas = new FakeCanvas({ '2d': fake.ctx });
	const renderer = createCanvas2dRenderer(canvas as unknown as HTMLCanvasElement);
	assert.ok(renderer);
	assert.equal(renderer.kind, 'canvas2d');
	renderer.resize(400, 300, 1);
	renderer.setPoints(three(), [0, 0, 0]);
	renderer.render({ matrix, pointSizePx: 6, dpr: 1 });
	assert.equal(fake.count('arc'), 2 + 1, 'two filled points, plus the outline of the outlined one');
	assert.ok(fake.count('fill') >= 2);
	assert.equal(fake.count('stroke'), 1);
});

// -----------------------------------------------------------------------------
// Overlay
// -----------------------------------------------------------------------------

const screen = (i: number): [number, number] | null => (i === 9 ? null : [i * 10, i * 5]);
const place = (p: { x: number; y: number }): [number, number] => [p.x, p.y];
const colours = { accent: '#0078d4', outline: '#1a1a1a', other: '#666666', text: '#1a1a1a', surface: '#ffffff' };

/** An overlay with nothing to draw. */
function empty(): IOverlayModel {
	return { hovered: null, selected: null, focused: null, highlight: [], neighbours: [], hollow: [], star: null, rays: [], chunkPath: [], duplicates: [], outliers: [], lasso: [], pulse: 0 };
}

test('an empty overlay draws nothing', () => {
	const fake = fake2d();
	drawOverlay(fake.ctx, empty(), screen, place, colours, 1);
	assert.equal(fake.count('stroke') + fake.count('fill'), 0);
});

test('the star, one ray per true top-k result, and the selection ring are drawn in the accent', () => {
	const fake = fake2d();
	drawOverlay(fake.ctx, { ...empty(), selected: 2, star: { x: 100, y: 100, exact: true }, rays: [{ index: 1 }, { index: 3 }, { at: { x: 5, y: 5 } }] }, screen, place, colours, 1);
	assert.equal(fake.count('lineTo') >= 3 + 9, true, 'three rays plus the star outline');
	assert.ok(fake.sets.some(([k, v]) => k === 'strokeStyle' && v === colours.accent));
	assert.ok(fake.count('arc') >= 1, 'selection ring');
});

test('duplicates are dashed, the chunk path is a polyline in chunk order, the lasso is closed, and points off screen are skipped', () => {
	const fake = fake2d();
	drawOverlay(fake.ctx, { ...empty(), duplicates: [[1, 2], [3, 9]], chunkPath: [1, 2, 3, 9, 4], lasso: [0, 0, 50, 0, 50, 50] }, screen, place, colours, 1);
	const dashes = fake.calls.filter((c) => c.name === 'setLineDash');
	assert.ok(dashes.some((c) => (c.args[0] as number[]).length > 0), 'a dashed line');
	assert.ok(fake.count('closePath') >= 1, 'the lasso is closed');
	// The duplicate pair with an off-screen end is not drawn: only one moveTo for duplicates.
	assert.ok(fake.count('moveTo') >= 3);
});

test('the overlay reports what it drew, not what it was asked for: the star, rays and links whose ends are on screen, chunk-path points on a drawn segment', () => {
	assert.deepEqual(drawOverlay(fake2d().ctx, empty(), screen, place, colours, 1), { star: false, rays: 0, links: 0, chunkPath: 0 });
	const asked: IOverlayModel = {
		...empty(),
		selected: 2,
		// 9 is off screen; an end with neither index nor place resolves to nothing.
		neighbours: [{ index: 1 }, { index: 9 }, { at: { x: 5, y: 5 } }, {}],
		star: { x: 100, y: 100, exact: true },
		rays: [{ index: 1 }, { index: 9 }, { index: 3 }],
		// Segments 1-2 and 5-6 are drawn; 4 sits between two off-screen points and joins nothing.
		chunkPath: [1, 2, 9, 4, 9, 5, 6],
	};
	assert.deepEqual(drawOverlay(fake2d().ctx, asked, screen, place, colours, 1), { star: true, rays: 2, links: 2, chunkPath: 4 });
	// The selected point itself off screen: no link is drawn, whatever was asked.
	assert.equal(drawOverlay(fake2d().ctx, { ...empty(), selected: 9, neighbours: [{ index: 1 }] }, screen, place, colours, 1).links, 0);
	// A star that cannot be placed draws neither itself nor its rays.
	const nowhere = (p: { x: number; y: number }): [number, number] | null => (Number.isFinite(p.x) ? [p.x, p.y] : null);
	assert.deepEqual(drawOverlay(fake2d().ctx, { ...empty(), star: { x: NaN, y: 0, exact: true }, rays: [{ index: 1 }] }, screen, nowhere, colours, 1), { star: false, rays: 0, links: 0, chunkPath: 0 });
	// A one-point path is not a path.
	assert.equal(drawOverlay(fake2d().ctx, { ...empty(), chunkPath: [3] }, screen, place, colours, 1).chunkPath, 0);
});

test('what the overlay drew becomes the canvas root\'s data attributes (data-star, data-rays, data-links, data-chunk-path)', () => {
	assert.deepEqual(overlayDataset({ star: true, rays: 10, links: 12, chunkPath: 7 }), { star: '1', rays: '10', links: '12', chunkPath: '7' });
	assert.deepEqual(overlayDataset({ star: false, rays: 0, links: 0, chunkPath: 0 }), { star: '0', rays: '0', links: '0', chunkPath: '0' });
});
