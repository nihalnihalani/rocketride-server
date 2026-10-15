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
// MAP - POINT COLOURS (pure: categories, ramps, "Other" and outlines)
// =============================================================================
//
// Colour is never the only carrier: the legend names every colour, the tooltip,
// inspector and Table say what a point is, and any colour that falls below 3:1
// on the map's surfaces is drawn with a 1 px outline (OUTLINE_TOKEN).
//
//   - Categories (document, folder, file type): the ten largest in the sample
//     take the six chart colours, then hashed hues whose lightness is moved until
//     they clear 3:1 on both surfaces of the current theme; the rest are "Other".
//   - Ramps (chunk position, query similarity, density): seven steps from a cool
//     to a warm hue, each moved to clear 3:1 as well.
// =============================================================================

import type { ColourBy, ISampleResult } from '../contract/types';
import { hslToRgb, minContrast, opaqueOver, parseColor, stableHash, toCss } from './contrast';
import type { Rgb } from './contrast';
import { MIN_GRAPHIC_CONTRAST } from './tokens';
import type { IMapPalette } from './tokens';

/** Categories that get their own colour. */
export const TOP_CATEGORIES = 10;

/** One category's colour. */
export interface ICategoryColour {
	/** Opaque CSS colour. */
	colour: string;
	/** True when the colour is below 3:1 on a surface and is drawn with an outline. */
	outlined: boolean;
}

/** One legend row. */
export interface ILegendEntry {
	/** Category key (objectId for documents), or 'other'. */
	key: string;
	label: string;
	colour: string;
	/** Visible points in the category. */
	count: number;
	outlined: boolean;
}

/** The colours of a sample. */
export interface IColouring {
	/** One opaque CSS colour per point. */
	colours: string[];
	/** The same, as RGBA bytes (4 per point) for the renderer. */
	rgba: Uint8Array;
	/** 1 for a point drawn with the outline. */
	outlined: Uint8Array;
	/** Category rows (empty for ramps). */
	legend: ILegendEntry[];
	/** The ramp of a sequential mode, or null. */
	ramp: { stops: string[]; low: string; high: string } | null;
	/** A sentence when the mode has nothing to show (no query yet). */
	note: string | null;
}

/** The two surfaces, parsed. */
function surfacesOf(palette: IMapPalette): Rgb[] {
	const bg = parseColor(palette.surfaces.default) ?? { r: 255, g: 255, b: 255 };
	const paper = opaqueOver(palette.surfaces.paper, bg) ?? bg;
	return [bg, paper];
}

/**
 * The first lightness (moving away from the background) at which a hue clears 3:1 on both surfaces.
 *
 * @param hue - Degrees.
 * @param palette - The theme.
 * @param start - Starting lightness, percent.
 * @returns The colour (outlined only when no lightness works).
 */
function readableHue(hue: number, palette: IMapPalette, start?: number): ICategoryColour {
	const surfaces = surfacesOf(palette);
	const dark = palette.mode === 'dark';
	const first = start ?? (dark ? 60 : 42);
	for (let l = first; dark ? l <= 94 : l >= 8; l += dark ? 2 : -2) {
		const rgb = hslToRgb(hue, 0.65, l / 100);
		if (minContrast(rgb, surfaces) >= MIN_GRAPHIC_CONTRAST) return { colour: toCss(rgb), outlined: false };
	}
	return { colour: toCss(hslToRgb(hue, 0.65, first / 100)), outlined: true };
}

/**
 * The colour of a category slot.
 *
 * @param slot - 0-based rank among the top categories.
 * @param hashKey - What a hashed slot's hue is derived from.
 * @param palette - The theme.
 * @param hueOverride - Force a hue for a hashed slot (tests sweep every hue).
 * @returns The colour.
 */
export function categoricalColour(slot: number, hashKey: string, palette: IMapPalette, hueOverride?: number): ICategoryColour {
	if (slot < palette.chart.length) {
		const surfaces = surfacesOf(palette);
		const rgb = opaqueOver(palette.chart[slot] as string, surfaces[0] as Rgb) ?? { r: 128, g: 128, b: 128 };
		return { colour: toCss(rgb), outlined: minContrast(rgb, surfaces) < MIN_GRAPHIC_CONTRAST };
	}
	return readableHue(hueOverride ?? stableHash(hashKey) % 360, palette);
}

/** Hues of the sequential ramp, cool to warm. */
const RAMP_HUES = [230, 255, 280, 305, 330, 355, 22];

/**
 * The steps of the sequential ramp for a theme (low to high), each clearing 3:1.
 *
 * @param palette - The theme.
 * @returns Opaque CSS colours.
 */
export function rampStops(palette: IMapPalette): string[] {
	const dark = palette.mode === 'dark';
	return RAMP_HUES.map((hue, i) => readableHue(hue, palette, dark ? 54 + 3 * i : 46 - 2 * i).colour);
}

/** The last path segment. */
function baseName(path: string): string {
	const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
	return cut >= 0 ? path.slice(cut + 1) : path;
}

/**
 * The category of a document path.
 *
 * @param by - 'document' (base name), 'folder' (directory; bare names are "Uploaded") or 'type' (extension).
 * @param path - The document path as stored.
 * @returns The category label.
 */
export function categoryOf(by: 'document' | 'folder' | 'type', path: string): string {
	if (by === 'document') return baseName(path) || path;
	if (by === 'folder') {
		const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
		return cut > 0 ? path.slice(0, cut) : 'Uploaded';
	}
	const name = baseName(path);
	const dot = name.lastIndexOf('.');
	return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toLowerCase() : 'no extension';
}

/** Nouns for the "Other" row. */
const OTHER_NOUN: Record<'document' | 'folder' | 'type', [string, string]> = { document: ['document', 'documents'], folder: ['folder', 'folders'], type: ['type', 'types'] };

/** Ramp ends per mode. */
const RAMP_ENDS: Record<'chunk-position' | 'query-similarity' | 'density', [string, string]> = {
	'chunk-position': ['first chunk', 'last chunk'],
	'query-similarity': ['least similar', 'most similar'],
	density: ['sparse', 'dense'],
};

/**
 * Colour every point of a sample.
 *
 * @param sample - The `sample` answer.
 * @param by - The colour mode.
 * @param palette - The theme.
 * @param options - Query similarities (for 'query-similarity') and the hidden mask.
 * @returns Colours, outlines, legend and ramp.
 */
export function colourPoints(sample: ISampleResult, by: ColourBy, palette: IMapPalette, options: { querySims?: ArrayLike<number> | null; hidden?: ArrayLike<number> | null } = {}): IColouring {
	const n = sample.n;
	const hidden = options.hidden ?? null;
	const visible = (i: number): boolean => !(hidden != null && (hidden[i] as number) !== 0);
	const surfaces = surfacesOf(palette);
	const other = toCss(opaqueOver(palette.other, surfaces[0] as Rgb) ?? { r: 128, g: 128, b: 128 });
	const colours = new Array<string>(n).fill(other);
	let legend: ILegendEntry[] = [];
	let ramp: IColouring['ramp'] = null;
	let note: string | null = null;

	if (by === 'document' || by === 'folder' || by === 'type') {
		const keyOfDoc = sample.docs.map((d) => (by === 'document' ? d.objectId : categoryOf(by, d.path)));
		const labelOfDoc = sample.docs.map((d) => categoryOf(by, d.path));
		const counts = new Map<string, { label: string; count: number }>();
		for (let i = 0; i < n; i += 1) {
			if (!visible(i)) continue;
			const d = sample.points.doc[i] as number;
			const key = keyOfDoc[d] as string;
			const row = counts.get(key);
			if (row) row.count += 1;
			else counts.set(key, { label: labelOfDoc[d] as string, count: 1 });
		}
		const ranked = [...counts.entries()].sort((a, b) => b[1].count - a[1].count || (a[1].label < b[1].label ? -1 : a[1].label > b[1].label ? 1 : 0) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
		const slotColour = new Map<string, ICategoryColour>();
		ranked.slice(0, TOP_CATEGORIES).forEach(([key], slot) => slotColour.set(key, categoricalColour(slot, key, palette)));
		for (let i = 0; i < n; i += 1) {
			const c = slotColour.get(keyOfDoc[sample.points.doc[i] as number] as string);
			if (c) colours[i] = c.colour;
		}
		legend = ranked.slice(0, TOP_CATEGORIES).map(([key, row]) => {
			const c = slotColour.get(key) as ICategoryColour;
			return { key, label: row.label, colour: c.colour, count: row.count, outlined: false };
		});
		const rest = ranked.slice(TOP_CATEGORIES);
		if (rest.length > 0) {
			const [one, many] = OTHER_NOUN[by];
			legend.push({ key: 'other', label: `Other (${rest.length.toLocaleString('en-US')} ${rest.length === 1 ? one : many})`, colour: other, count: rest.reduce((s, [, row]) => s + row.count, 0), outlined: false });
		}
	} else {
		const values = new Float64Array(n).fill(Number.NaN);
		if (by === 'chunk-position') {
			const maxChunk = new Map<number, number>();
			for (let i = 0; i < n; i += 1) maxChunk.set(sample.points.doc[i] as number, Math.max(maxChunk.get(sample.points.doc[i] as number) ?? 0, sample.points.chunk[i] as number));
			for (let i = 0; i < n; i += 1) {
				const d = sample.points.doc[i] as number;
				const total = sample.docs[d]?.chunks ?? (maxChunk.get(d) ?? 0) + 1;
				values[i] = Math.min(1, (sample.points.chunk[i] as number) / Math.max(1, total - 1));
			}
		} else {
			const source = by === 'density' ? sample.density : options.querySims ?? null;
			if (source === null || source.length < n) {
				note = 'Run a text query to colour the points by their similarity to it.';
			} else if (by === 'density') {
				// Rank-normalised, so a few extreme values do not flatten the rest.
				const order = Array.from({ length: n }, (_, i) => i).filter(visible).sort((a, b) => (source[a] as number) - (source[b] as number) || a - b);
				order.forEach((i, rank) => (values[i] = order.length > 1 ? rank / (order.length - 1) : 1));
			} else {
				let lo = Infinity;
				let hi = -Infinity;
				for (let i = 0; i < n; i += 1) {
					if (!visible(i)) continue;
					lo = Math.min(lo, source[i] as number);
					hi = Math.max(hi, source[i] as number);
				}
				for (let i = 0; i < n; i += 1) values[i] = hi > lo ? ((source[i] as number) - lo) / (hi - lo) : 1;
			}
		}
		if (note === null) {
			const stops = rampStops(palette);
			for (let i = 0; i < n; i += 1) {
				const v = values[i] as number;
				if (Number.isFinite(v)) colours[i] = stops[Math.min(stops.length - 1, Math.max(0, Math.floor(v * stops.length)))] as string;
			}
			const [low, high] = RAMP_ENDS[by];
			ramp = { stops, low, high };
		}
	}

	const rgba = new Uint8Array(n * 4);
	const outlined = new Uint8Array(n);
	const weak = new Map<string, boolean>();
	for (let i = 0; i < n; i += 1) {
		const text = colours[i] as string;
		const rgb = parseColor(text) as Rgb;
		let w = weak.get(text);
		if (w === undefined) {
			w = minContrast(rgb, surfaces) < MIN_GRAPHIC_CONTRAST;
			weak.set(text, w);
		}
		rgba[4 * i] = rgb.r;
		rgba[4 * i + 1] = rgb.g;
		rgba[4 * i + 2] = rgb.b;
		rgba[4 * i + 3] = 255;
		outlined[i] = w ? 1 : 0;
	}
	for (const entry of legend) entry.outlined = weak.get(entry.colour) ?? false;
	return { colours, rgba, outlined, legend, ramp, note };
}
