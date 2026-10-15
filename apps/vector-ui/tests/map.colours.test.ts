// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP COLOURS: categories, ramps, the "Other" bucket and outlines
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { TOP_CATEGORIES, categoryOf, colourPoints } from '../src/map/colours';
import { contrastRatio, parseColor } from '../src/map/contrast';
import { MIN_GRAPHIC_CONTRAST, readPalette } from '../src/map/tokens';
import type { IMapPalette } from '../src/map/tokens';
import { loadSample } from './support/map.samples';

const THEME_DIR = path.resolve(__dirname, '..', '..', '..', 'packages', 'shell', 'public', 'themes');
const theme = (name: string): IMapPalette => {
	const tokens = JSON.parse(fs.readFileSync(path.join(THEME_DIR, `${name}.json`), 'utf8')) as Record<string, string>;
	return readPalette((token) => tokens[token] ?? '');
};
const demo = loadSample('sample_demo_1000.json');

test('colour by document: the ten largest documents get their own colour, everything else is "Other"', () => {
	const out = colourPoints(demo, 'document', theme('rocketride'));
	assert.equal(out.colours.length, demo.n);
	assert.equal(out.rgba.length, demo.n * 4);
	const named = out.legend.filter((e) => e.key !== 'other');
	assert.equal(named.length, TOP_CATEGORIES);
	// Largest first; counts add up to every point.
	for (let i = 1; i < named.length; i += 1) assert.ok((named[i - 1]?.count as number) >= (named[i]?.count as number));
	assert.equal(out.legend.reduce((s, e) => s + e.count, 0), demo.n);
	assert.equal(named[0]?.label, 'ops_005.pdf');
	assert.equal(named[0]?.count, 70);
	const other = out.legend.find((e) => e.key === 'other');
	assert.equal(other?.label, 'Other (32 documents)');
	// Every point of a document shares its colour.
	const first = demo.points.doc.indexOf(27);
	for (let i = 0; i < demo.n; i += 1) if (demo.points.doc[i] === 27) assert.equal(out.colours[i], out.colours[first]);
	// Same input, same colours.
	assert.deepEqual(colourPoints(demo, 'document', theme('rocketride')).colours, out.colours);
});

test('categories: folder from / or \\ paths, bare names under "Uploaded"; type from the extension', () => {
	assert.equal(categoryOf('folder', 'C:/demo/field/a.md'), 'C:/demo/field');
	assert.equal(categoryOf('folder', 'C:\\share\\b.pdf'), 'C:\\share');
	assert.equal(categoryOf('folder', 'report.pdf'), 'Uploaded');
	assert.equal(categoryOf('type', 'C:/x/Report.PDF'), 'pdf');
	assert.equal(categoryOf('type', 'C:/x/README'), 'no extension');
	const out = colourPoints(demo, 'folder', theme('light'));
	assert.deepEqual(out.legend.map((e) => e.label).sort(), ['C:/demo/field', 'C:/demo/finance', 'C:/demo/greenhouse', 'C:/demo/handbooks', 'C:/demo/legal', 'C:/demo/ops', 'C:/demo/research', 'C:/demo/support']);
	const types = colourPoints(demo, 'type', theme('light'));
	assert.deepEqual(types.legend.map((e) => e.label).sort(), ['docx', 'md', 'pdf', 'txt']);
});

test('ramps: chunk position, density and query similarity map low to high in order, with a legend ramp', () => {
	const palette = theme('rocketride-light');
	const sims = demo.points.x.map((x) => x);
	const byQuery = colourPoints(demo, 'query-similarity', palette, { querySims: sims });
	assert.ok(byQuery.ramp && byQuery.ramp.stops.length >= 5);
	assert.equal(byQuery.ramp?.low, 'least similar');
	assert.equal(byQuery.ramp?.high, 'most similar');
	// The point with the highest similarity gets the last stop, the lowest the first.
	const hi = sims.indexOf(Math.max(...sims));
	const lo = sims.indexOf(Math.min(...sims));
	assert.equal(byQuery.colours[hi], byQuery.ramp?.stops.at(-1));
	assert.equal(byQuery.colours[lo], byQuery.ramp?.stops[0]);
	const noQuery = colourPoints(demo, 'query-similarity', palette);
	assert.equal(noQuery.note, 'Run a text query to colour the points by their similarity to it.');
	assert.equal(new Set(noQuery.colours).size, 1);
	const position = colourPoints(demo, 'chunk-position', palette);
	const firstChunk = demo.points.chunk.indexOf(0);
	assert.equal(position.colours[firstChunk], position.ramp?.stops[0]);
	assert.ok(colourPoints(demo, 'density', palette).ramp);
});

test('a colour below 3:1 on either surface is drawn with an outline; one that clears it is not', () => {
	for (const name of ['light', 'rocketride-light', 'rocketride', 'gray', 'dark', 'visual-studio']) {
		const palette = theme(name);
		const out = colourPoints(demo, 'document', palette);
		const surfaces = [palette.surfaces.default, palette.surfaces.paper].map((c) => parseColor(c)!);
		for (let i = 0; i < demo.n; i += 1) {
			const rgb = parseColor(out.colours[i] as string)!;
			const weak = surfaces.some((s) => contrastRatio(rgb, s) < MIN_GRAPHIC_CONTRAST);
			assert.equal(out.outlined[i], weak ? 1 : 0, `${name}: point ${i} ${out.colours[i]}`);
		}
	}
});

test('hidden points keep their slot but are left out of the legend counts', () => {
	const hidden = new Uint8Array(demo.n);
	for (let i = 0; i < demo.n; i += 1) if (demo.points.doc[i] === 27) hidden[i] = 1;
	const out = colourPoints(demo, 'document', theme('dark'), { hidden });
	assert.equal(out.colours.length, demo.n);
	assert.equal(out.legend.reduce((s, e) => s + e.count, 0), demo.n - 70);
	assert.ok(!out.legend.some((e) => e.label === 'ops_005.pdf'));
});
