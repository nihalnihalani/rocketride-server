// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP PERF LANE: its gate logic, without a browser (it must never pass vacuously)
// =============================================================================
//
// scripts/acceptance/vector-explorer/browser/lane_vector_perf.cjs measures the
// map in Chrome at integration. Its pure parts are exported; these tests pin
// that the 2,000-point gate fails when the row is missing, errored, too short
// or too slow, and passes only on a real measurement.
// =============================================================================

import assert from 'node:assert/strict';
import path from 'node:path';
import { test } from 'node:test';

interface IRow {
	n: number;
	mode: string;
	cpuThrottle: number;
	error?: string;
	panFrameMs?: { samples: number; p50: number | null; p95: number | null; max: number | null };
	neighbourLayout?: { state: string; overlap: number | null; pcaOverlap: number | null };
	steps?: Array<{ name: string; status: string }>;
}
interface ILane {
	GATE: { n: number; mode: string; rate: number; maxP95: number; minSamples: number };
	pct(values: number[], p: number): number | null;
	parseSizes(text: string): Array<{ n: number; mode: string }>;
	summarise(frames: number[]): { samples: number; p50: number | null; p95: number | null; max: number | null };
	evaluateGates(rows: IRow[]): Array<{ name: string; status: 'PASS' | 'FAIL'; detail: string }>;
}

const lane = require(path.resolve(__dirname, '..', '..', '..', 'scripts', 'acceptance', 'vector-explorer', 'browser', 'lane_vector_perf.cjs')) as ILane;

const frames = (count: number, ms: number): number[] => Array.from({ length: count }, () => ms);
const gateRow = (extra: Partial<IRow> = {}): IRow => ({ n: 2000, mode: 'detailed', cpuThrottle: 4, panFrameMs: lane.summarise(frames(80, 18)), ...extra });

test('the gate is 2,000 detailed points at 4x CPU throttling, p95 frame interval at most 33 ms', () => {
	assert.deepEqual({ n: lane.GATE.n, mode: lane.GATE.mode, rate: lane.GATE.rate, maxP95: lane.GATE.maxP95 }, { n: 2000, mode: 'detailed', rate: 4, maxP95: 33 });
});

test('percentiles and summaries match the Graph Explorer lane\'s definition', () => {
	assert.equal(lane.pct([], 95), null);
	assert.equal(lane.pct(Array.from({ length: 100 }, (_, i) => i + 1), 95), 96);
	assert.deepEqual(lane.summarise([10, 20, 30, 40]), { samples: 4, p50: 30, p95: 40, max: 40 });
	assert.deepEqual(lane.parseSizes('500, 1000,light:5000'), [{ n: 500, mode: 'detailed' }, { n: 1000, mode: 'detailed' }, { n: 5000, mode: 'light' }]);
});

test('a real, fast measurement passes the gate', () => {
	const gates = lane.evaluateGates([gateRow()]);
	const gate = gates.find((g) => g.name.startsWith('GATE'));
	assert.equal(gate?.status, 'PASS', gate?.detail);
});

test('the gate fails when it was not measured, errored, measured too few frames, or was too slow', () => {
	const cases: Array<[string, IRow[]]> = [
		['no rows', []],
		['only other sizes', [gateRow({ n: 1000 })]],
		['only 1x', [gateRow({ cpuThrottle: 1 })]],
		['errored', [gateRow({ error: 'canvas never drew' })]],
		['too few frames', [gateRow({ panFrameMs: lane.summarise(frames(5, 16)) })]],
		['too slow', [gateRow({ panFrameMs: lane.summarise([...frames(70, 16), ...frames(10, 50)]) })]],
		['no frames object', [gateRow({ panFrameMs: undefined })]],
	];
	for (const [what, rows] of cases) {
		const gate = lane.evaluateGates(rows).find((g) => g.name.startsWith('GATE'));
		assert.equal(gate?.status, 'FAIL', what);
	}
});

test('a neighbour layout shown although it keeps less than PCA, or a failed map step, fails the lane', () => {
	const kept = lane.evaluateGates([gateRow({ neighbourLayout: { state: 'done', overlap: 0.2, pcaOverlap: 0.3 } })]);
	assert.ok(kept.some((g) => g.status === 'FAIL' && /neighbour layout/.test(g.name)));
	const fine = lane.evaluateGates([gateRow({ neighbourLayout: { state: 'kept-pca', overlap: 0.2, pcaOverlap: 0.3 } })]);
	assert.ok(fine.every((g) => !/neighbour layout/.test(g.name) || g.status === 'PASS'));
	const step = lane.evaluateGates([gateRow({ steps: [{ name: 'hover shows a tooltip', status: 'FAIL' }] })]);
	assert.ok(step.some((g) => g.status === 'FAIL' && /hover shows a tooltip/.test(g.name)));
});
