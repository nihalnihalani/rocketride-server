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
// VECTOR - COLLECTION CHARTS (pure): the bins of the stats strip's four charts
// =============================================================================
//
// Four small charts over what the console already holds, with no call of
// their own: chunks per document (powers-of-two bins over the directory's
// loaded rows), chunk length (from the map's sample, its pinned points left
// out), documents by file type, and documents ingested over time (by day,
// week or month by the span). Each says where its numbers come from and how
// much of the collection that is ("5 of 42 documents loaded"), never an
// estimate; a bar whose documents the store can be asked for carries the
// scope a click applies (a chunk range, a file type, a period).
// =============================================================================

import type { IDialectResult, IDocumentItem, IDocumentsFilter, ISampleModel } from '../contract/types';
import { extensionOf } from './fileType';
import { isFilterExtension } from './filters';

// =============================================================================
// BINS
// =============================================================================

/** One bar. */
export interface IBin {
	key: string;
	label: string;
	/** Inclusive bounds (integers for counts and lengths; epoch ms for periods). */
	lo: number;
	hi: number;
	count: number;
	/** The scope a click on it applies, or null when the store cannot be asked for it. */
	scope: IDocumentsFilter | null;
}

/**
 * The median.
 *
 * @param values - Numbers.
 * @returns The middle value (the mean of the two middles), or null for none.
 */
export function median(values: readonly number[]): number | null {
	if (values.length === 0) return null;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 === 1 ? (sorted[mid] as number) : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

/**
 * Count values per bin: bin i holds [edges[i], edges[i + 1]); the last bin is
 * open above; values below the first edge are not counted.
 *
 * @param values - Numbers.
 * @param edges - Ascending lower edges.
 * @returns The counts, one per edge.
 */
export function binCounts(values: readonly number[], edges: readonly number[]): number[] {
	const counts = edges.map(() => 0);
	for (const v of values) {
		if (edges.length === 0 || v < (edges[0] as number)) continue;
		let lo = 0;
		let hi = edges.length - 1;
		while (lo < hi) {
			const mid = (lo + hi + 1) >> 1;
			if ((edges[mid] as number) <= v) lo = mid;
			else hi = mid - 1;
		}
		counts[lo] = (counts[lo] as number) + 1;
	}
	return counts;
}

/** A range in words: '1', '2–3'. */
function rangeLabel(lo: number, hi: number): string {
	return lo === hi ? lo.toLocaleString('en-US') : `${lo.toLocaleString('en-US')}–${hi.toLocaleString('en-US')}`;
}

/**
 * Powers-of-two bins over counts (0; 1; 2–3; 4–7; …), contiguous from 1 (or 0
 * when a value is 0) to the bin of the largest value, empty bins kept.
 *
 * @param values - Non-negative integers.
 * @returns The bins (none for no values); each scopes to its range of chunks.
 */
export function logBins(values: readonly number[]): IBin[] {
	if (values.length === 0) return [];
	const max = Math.max(...values);
	const lows: number[] = values.some((v) => v < 1) ? [0] : [];
	for (let lo = 1; lo <= Math.max(1, max); lo *= 2) lows.push(lo);
	const counts = binCounts(values, lows);
	return lows.map((lo, i) => {
		const hi = lo === 0 ? 0 : lo * 2 - 1;
		return { key: `c${lo}`, label: rangeLabel(lo, hi), lo, hi, count: counts[i] as number, scope: { min_chunks: lo, max_chunks: hi } };
	});
}

/**
 * The step of at most `target` bins over [0, max]: 1, 2 or 5 times a power of ten.
 *
 * @param max - The largest value.
 * @param target - Bins wanted at most.
 * @returns The step (≥ 1).
 */
function niceStep(max: number, target: number): number {
	const raw = Math.max(1, max / target);
	const power = 10 ** Math.floor(Math.log10(raw));
	for (const m of [1, 2, 5, 10]) if (m * power >= raw) return m * power;
	return 10 * power;
}

/**
 * Equal-width bins of chunk lengths from 0 (at most 12, round widths).
 *
 * @param lengths - Characters per chunk.
 * @returns The bins (not scopes: the store cannot filter by length).
 */
export function lengthBins(lengths: readonly number[]): IBin[] {
	if (lengths.length === 0) return [];
	const max = Math.max(...lengths);
	const step = niceStep(max + 1, 10);
	const lows: number[] = [];
	for (let lo = 0; lo <= max; lo += step) lows.push(lo);
	const counts = binCounts(lengths, lows);
	return lows.map((lo, i) => ({ key: `l${lo}`, label: rangeLabel(lo, lo + step - 1), lo, hi: lo + step - 1, count: counts[i] as number, scope: null }));
}

/**
 * Documents by the extension of their file name (Windows, POSIX, share and
 * bare names alike): the most common first, ties by name; past `top` rows the
 * rest are one "other" bar.
 *
 * @param rows - The loaded documents.
 * @param top - Bars at most (default 8).
 * @returns The bins; a type's bar scopes to it when the node accepts it as an extension (not '15 meeting' from
 *   'Board 2026.10.15 meeting', 'db_old' or 'json-ld'; those bars are drawn, not clickable).
 */
export function byFileType(rows: readonly IDocumentItem[], top = 8): IBin[] {
	const NONE = '(no extension)';
	const counts = new Map<string, number>();
	for (const row of rows) {
		const ext = extensionOf(row.path) ?? NONE;
		counts.set(ext, (counts.get(ext) ?? 0) + 1);
	}
	const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
	const bin = (ext: string, count: number, i: number): IBin => ({ key: `t${ext}`, label: ext, lo: i, hi: i, count, scope: ext !== NONE && isFilterExtension(ext) ? { file_types: [ext] } : null });
	if (sorted.length <= top) return sorted.map(([ext, count], i) => bin(ext, count, i));
	const kept = sorted.slice(0, top - 1).map(([ext, count], i) => bin(ext, count, i));
	const rest = sorted.slice(top - 1);
	kept.push({ key: 'tother', label: `other (${rest.length} types)`, lo: top - 1, hi: top - 1, count: rest.reduce((sum, [, n]) => sum + n, 0), scope: null });
	return kept;
}

// =============================================================================
// PERIODS
// =============================================================================

const DAY_MS = 86_400_000;

/** How the ingest chart groups time. */
export type PeriodUnit = 'day' | 'week' | 'month';

/** The start of the UTC period holding a time. */
function periodStart(ms: number, unit: PeriodUnit): number {
	const d = new Date(ms);
	if (unit === 'month') return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
	const day = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
	if (unit === 'day') return day;
	return day - ((d.getUTCDay() + 6) % 7) * DAY_MS;
}

/** The start of the next period. */
function periodNext(start: number, unit: PeriodUnit): number {
	if (unit === 'day') return start + DAY_MS;
	if (unit === 'week') return start + 7 * DAY_MS;
	const d = new Date(start);
	return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
}

/** An ISO time without milliseconds. */
function iso(ms: number): string {
	return new Date(ms).toISOString().replace('.000Z', 'Z');
}

/**
 * Documents ingested per day (span within 31 days), week (Monday, UTC; within
 * 26 weeks) or month, every period from the first to the last kept.
 *
 * @param rows - The loaded documents.
 * @returns The unit, the bins (each scopes to its period) and how many rows had an ingest time.
 */
export function byIngestPeriod(rows: readonly IDocumentItem[]): { unit: PeriodUnit; bins: IBin[]; dated: number } {
	const times: number[] = [];
	for (const row of rows) {
		if (row.ingestedAt === null) continue;
		const at = Date.parse(row.ingestedAt);
		if (Number.isFinite(at)) times.push(at);
	}
	if (times.length === 0) return { unit: 'day', bins: [], dated: 0 };
	const min = Math.min(...times);
	const max = Math.max(...times);
	const spanDays = (periodStart(max, 'day') - periodStart(min, 'day')) / DAY_MS;
	const unit: PeriodUnit = spanDays <= 31 ? 'day' : spanDays <= 7 * 26 ? 'week' : 'month';
	const starts: number[] = [];
	for (let s = periodStart(min, unit); s <= max; s = periodNext(s, unit)) starts.push(s);
	const counts = binCounts(times, starts);
	const bins = starts.map((start, i) => {
		const next = periodNext(start, unit);
		const day = iso(start).slice(0, 10);
		const label = unit === 'day' ? day : unit === 'week' ? `week of ${day}` : day.slice(0, 7);
		return { key: `p${start}`, label, lo: start, hi: next - 1, count: counts[i] as number, scope: { ingested_after: iso(start), ingested_before: iso(next) } };
	});
	return { unit, bins, dated: times.length };
}

// =============================================================================
// THE FOUR CHARTS
// =============================================================================

/** One chart of the strip. */
export interface IChart {
	id: 'chunks' | 'length' | 'types' | 'ingest';
	title: string;
	/** What the bars count ('documents', 'chunks'). */
	unit: string;
	bins: IBin[];
	/** Source and coverage. */
	caption: string;
	/** The text alternative (the figure's aria-label). */
	summary: string;
	/** Why the chart cannot be drawn, or null. */
	disabled: string | null;
	/** The directory is still loading (skeleton bars until it has rows). */
	loading: boolean;
	median: number | null;
}

/** What the charts read. */
export interface IChartsInput {
	/** The directory's loaded rows. */
	rows: readonly IDocumentItem[];
	/** Documents the store holds, when it counted them. */
	total: number | null;
	/** The map's sample, or null. */
	sample: ISampleModel | null;
	dialect: IDialectResult | null;
	/** The directory is still loading pages. */
	loading: boolean;
}

/** A number with its noun. */
function plural(n: number, one: string, many: string): string {
	return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
}

/** A median in words (one decimal at most). */
function medianText(m: number): string {
	return (Math.round(m * 10) / 10).toLocaleString('en-US');
}

/** "5 of 42 documents loaded", or "5 documents" when everything is loaded. */
function coverage(loaded: number, total: number | null): string {
	return total !== null && total > loaded ? `${loaded.toLocaleString('en-US')} of ${plural(total, 'document', 'documents')} loaded` : plural(loaded, 'document', 'documents');
}

/**
 * The text alternative of a chart.
 *
 * @param title - The chart.
 * @param bins - Its bars.
 * @param unit - What the bars count.
 * @param suffix - Words after a bin's label ('chunks', '').
 * @returns e.g. 'Chunks per document, 4 documents in 7 bins: most in 4–7 (2); the top bin is 64–127 (1).'
 */
function summaryOf(title: string, bins: readonly IBin[], unit: string, suffix = ''): string {
	const total = bins.reduce((sum, b) => sum + b.count, 0);
	if (bins.length === 0 || total === 0) return `${title}: nothing to show.`;
	const most = bins.reduce((best, b) => (b.count > best.count ? b : best), bins[0] as IBin);
	const last = [...bins].reverse().find((b) => b.count > 0) as IBin;
	const tail = last === most ? '' : `; the top bin is ${last.label}${suffix} (${last.count.toLocaleString('en-US')})`;
	return `${title}, ${plural(total, unit.replace(/s$/, ''), unit)} in ${plural(bins.length, 'bin', 'bins')}: most in ${most.label}${suffix} (${most.count.toLocaleString('en-US')})${tail}.`;
}

/**
 * Chunks per document over the loaded rows.
 *
 * @param rows - The loaded rows.
 * @param total - Documents the store holds, when it counted them.
 * @returns The chart.
 */
export function chunksPerDocument(rows: readonly IDocumentItem[], total: number | null): IChart {
	const counted = rows.map((r) => r.chunks).filter((c): c is number => c !== null);
	const bins = logBins(counted);
	const m = median(counted);
	const parts = [coverage(rows.length, total)];
	if (m !== null) parts.push(`median ${medianText(m)} chunks`);
	if (counted.length < rows.length) parts.push(`${(rows.length - counted.length).toLocaleString('en-US')} without a count`);
	return {
		id: 'chunks',
		title: 'Chunks per document',
		unit: 'documents',
		bins,
		caption: parts.join(' · '),
		summary: summaryOf('Chunks per document', bins, 'documents'),
		disabled: rows.length > 0 && counted.length === 0 ? 'This store does not count chunks per document' : null,
		loading: false,
		median: m,
	};
}

/**
 * The stats strip's four charts.
 *
 * @param input - The loaded rows, the store's total, the map's sample, the dialect and whether the directory is loading.
 * @returns Chunks per document, chunk length, documents by file type, ingested over time.
 */
export function collectionCharts(input: IChartsInput): IChart[] {
	const { rows, total, sample, dialect, loading } = input;
	const skeleton = loading && rows.length === 0;

	const chunks = { ...chunksPerDocument(rows, total), loading };

	let lengths: number[] = [];
	if (sample !== null) {
		const points = sample.result.points;
		lengths = points.len.filter((_, i) => points.pinned[i] !== 1);
	}
	const lengthChartBins = lengthBins(lengths);
	const lm = median(lengths);
	const length: IChart = {
		id: 'length',
		title: 'Chunk length',
		unit: 'chunks',
		bins: lengthChartBins,
		caption: sample === null ? '' : `from the map's sample of ${plural(lengths.length, 'chunk', 'chunks')}${lm === null ? '' : ` · median ${medianText(lm)} characters`}`,
		summary: summaryOf('Chunk length in characters', lengthChartBins, 'chunks'),
		disabled: sample === null || lengths.length === 0 ? "Draw the map's sample to see chunk lengths" : null,
		loading: false,
		median: lm,
	};

	const typeBins = byFileType(rows);
	const types: IChart = { id: 'types', title: 'Documents by file type', unit: 'documents', bins: typeBins, caption: coverage(rows.length, total), summary: summaryOf('Documents by file type', typeBins, 'documents'), disabled: null, loading, median: null };

	const caveats = new Set(dialect?.caveats ?? []);
	const periods = byIngestPeriod(rows);
	let ingestDisabled: string | null = null;
	if (caveats.has('extras_not_stored')) ingestDisabled = 'This store does not keep ingest times';
	else if (rows.length > 0 && periods.dated === 0) ingestDisabled = 'No ingest times on the loaded documents';
	const undated = rows.length - periods.dated;
	const ingest: IChart = {
		id: 'ingest',
		title: 'Ingested over time',
		unit: 'documents',
		bins: periods.bins,
		caption: `by ${periods.unit} · ${coverage(rows.length, total)}${undated > 0 && periods.dated > 0 ? ` · ${undated.toLocaleString('en-US')} without an ingest time` : ''}`,
		summary: summaryOf(`Documents ingested by ${periods.unit}`, periods.bins, 'documents'),
		disabled: ingestDisabled,
		loading,
		median: null,
	};

	return [chunks, length, types, ingest].map((chart) => (skeleton && chart.id !== 'length' ? { ...chart, loading: true } : chart));
}
