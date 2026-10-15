// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Vector Explorer map performance (and the map's own steps) in the real served
 * shell, Chrome via CDP.
 *
 * For each sample size (default 500, 1,000 and 2,000 detailed; 5,000 light) at
 * each CPU throttling rate (default 1x and 4x): time from choosing the size to
 * the points drawn, the points drawn (data-points), the renderer, frame
 * intervals while panning, hovering and zooming, the app's own draw-time p95,
 * the neighbour-graph layout's time and its kNN overlap next to PCA's
 * (data-knn-overlap / data-pca-overlap, both recorded), t-SNE's time up to
 * 1,000 points, and the JS heap.
 *
 * At 1x on the 1,000- and 5,000-point rows it also runs the map's steps: hover
 * shows a tooltip; a click lists 12 nearest chunks of the collection; the lasso
 * selects points and says how many; the keyboard path moves and Enter inspects;
 * the Table alternative lists the points; the legend names who computed the
 * neighbour graph; t-SNE is refused above 1,000 points; Cancel stops a layout;
 * a text query (when the embedding node answers) draws its star and rays.
 *
 * GATE: 2,000 detailed points at 4x CPU throttling, p95 frame interval while
 * panning <= 33 ms. A check that measured nothing FAILS: the frame intervals
 * count only when the pan really drew (a renderer runs, the canvas's
 * data-draw-count advanced by at least GATE.minSamples frames and its
 * data-camera moved), since requestAnimationFrame ticks at ~16.7 ms on an idle
 * page whether or not anything is drawn. A neighbour-graph or t-SNE layout
 * that failed, could not start or was refused fails its row; the neighbour
 * layout may only be shown when it keeps at least as much of each
 * neighbourhood as PCA (a run stopped by its 15 s budget is reported as
 * timedOut and judged like any other).
 *
 * PRIVACY (B4), on every row over that row's WebSocket frames: no response
 * carries a float array as long as dialect.dimension except `vectors` answers
 * (at most 2) and `embed` answers; no request carries one other than the
 * exact query vector an `embed` answer returned in the same session. The
 * check is L10's (common.cjs privacyViolations); dialect.dimension is the
 * store's own, read through the TypeScript client with the fixture's Tools
 * token. Nothing captured FAILS, and a row whose text query ran must have seen
 * that vector go out.
 *
 * Fixture: gen_perf.py (a disposable collection of >= 6,000 chunks; its card is
 * VX_PERF_FIXTURE, default "vx-local Map performance (Qdrant)", project id
 * VX_PERF_PROJECT_ID, default gen_perf.py's PERF_PROJECT_ID).
 *
 * Usage: node lane_vector_perf.cjs [base-url] [out-json|out-dir] [sizes] [rates]
 *   sizes: comma list of n (detailed) or light:n   (default 500,1000,2000,light:5000)
 *   rates: comma list of CPU throttling rates       (default 1,4)
 * vector-ui:e2e-live runs it as `node lane_vector_perf.cjs <base-url> <out-dir> <browser>`
 * and reads <out-dir>/lane_vector_perf.json (its `results` are the gate rows).
 * The lane drives Google Chrome only; another browser is one FAIL row.
 *   VX_PERF_QUERY: the text query of the query step (default "radio check-in schedule")
 * Exit code 0 only when every gate row passes.
 */
'use strict';
// page.evaluate() callbacks run in the browser.
/* global document, requestAnimationFrame, window */
const fs = require('fs');
const path = require('path');

/** The performance gate (PLAN G4). */
const GATE = { n: 2000, mode: 'detailed', rate: 4, maxP95: 33, minSamples: 30 };
const DEFAULT_SIZES = '500,1000,2000,light:5000';
const DEFAULT_RATES = '1,4';
const PERF_FIXTURE = process.env.VX_PERF_FIXTURE || 'vx-local Map performance (Qdrant)';
/** gen_perf.py PERF_PROJECT_ID (tests/map.perflane.test.ts keeps them equal). */
const PERF_PROJECT_ID = process.env.VX_PERF_PROJECT_ID || '00000000-0000-4000-8000-00000000d1a7';
const QUERY = process.env.VX_PERF_QUERY || 'radio check-in schedule';
const FINAL_LAYOUT_STATES = ['done', 'kept-pca', 'cancelled', 'refused', 'failed', 'unavailable'];
/** Layout outcomes of a run that worked (kept-pca: it ran and did not beat PCA, so PCA stays). */
const LAYOUT_RAN = ['done', 'kept-pca'];
/** Renderers that draw. */
const RENDERERS = ['webgl', 'canvas2d'];
/** The browsers vector-ui:e2e-live names (third argument); this lane drives Google Chrome only. */
const RUNNER_BROWSERS = ['chrome', 'firefox', 'webkit'];
/** The text-query step's name (its row must see the query vector go out). */
const QUERY_STEP = 'a text query draws its star and rays (when the embedding node answers)';

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests/map.perflane.test.ts)
// ---------------------------------------------------------------------------

/** The p-th percentile (Graph Explorer lane's definition: index floor(p% * n) of the sorted values). */
function pct(values, p) {
	if (!values.length) return null;
	const sorted = values.slice().sort((a, b) => a - b);
	return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))];
}

/** "500,light:5000" -> [{n: 500, mode: 'detailed'}, {n: 5000, mode: 'light'}]. */
function parseSizes(text) {
	return String(text)
		.split(',')
		.map((s) => s.trim())
		.filter(Boolean)
		.map((s) => {
			const [a, b] = s.split(':');
			return b === undefined ? { n: Number(a), mode: 'detailed' } : { n: Number(b), mode: a === 'light' ? 'light' : 'detailed' };
		});
}

/** Frame intervals -> { samples, p50, p95, max } (ms, one decimal). */
function summarise(frames) {
	const r = (v) => (v === null ? null : Math.round(v * 10) / 10);
	return { samples: frames.length, p50: r(pct(frames, 50)), p95: r(pct(frames, 95)), max: frames.length ? r(Math.max(...frames)) : null };
}

/** Why the gate row's pan proves no drawing (null when it does): a renderer ran, frames were drawn, the camera moved. */
function panWorkProblem(row) {
	if (!RENDERERS.includes(row.renderer)) return `no renderer draws the map (data-renderer ${JSON.stringify(row.renderer)})`;
	const work = row.panWork;
	if (!work) return 'the frames drawn during the pan were not read';
	if (!Number.isFinite(work.draws) || work.draws < GATE.minSamples) return `${work.draws} frames drawn during the pan (at least ${GATE.minSamples})`;
	if (!work.cameraBefore || !work.cameraAfter || work.cameraBefore === work.cameraAfter) return `the pan did not move the camera (${JSON.stringify(work.cameraBefore)} -> ${JSON.stringify(work.cameraAfter)})`;
	return null;
}

/** The B4 privacy row of one measured row. */
function privacyGate(row) {
	const name = `privacy (B4): no dialect.dimension-float array outside vectors / embed answers, none sent but the query's own (${row.mode} ${row.n} at ${row.cpuThrottle}x)`;
	const p = row.privacy;
	const fail = (detail) => ({ name, status: 'FAIL', detail });
	if (!p) return fail('not measured');
	if (!(p.frames > 0)) return fail('no WebSocket frames were captured');
	if (!Number.isInteger(p.dimension) || p.dimension <= 0) return fail(`dialect.dimension is unknown (${JSON.stringify(p.dimension)}${p.dimensionError ? `: ${p.dimensionError}` : ''})`);
	if (p.violations.length) return fail(p.violations.slice(0, 3).join('; '));
	const queried = (row.steps || []).some((s) => s.name === QUERY_STEP && s.status === 'PASS');
	if (queried && !(p.embedAnswers > 0 && p.vectorRequests > 0)) return fail(`the text query ran, but the capture saw ${p.embedAnswers} embed answers and ${p.vectorRequests} requests carrying the query vector`);
	return { name, status: 'PASS', detail: `${p.frames} frames, dimension ${p.dimension}, ${p.embedAnswers} embed answers, ${p.vectorRequests} requests carried the query vector` };
}

/** PASS/FAIL rows from the measured rows. Nothing measured is a FAIL, never a pass. */
function evaluateGates(rows) {
	const out = [];
	const gateRow = rows.find((r) => r.n === GATE.n && r.mode === GATE.mode && r.cpuThrottle === GATE.rate);
	const name = `GATE ${GATE.n.toLocaleString('en-US')} ${GATE.mode} points at ${GATE.rate}x: pan p95 frame <= ${GATE.maxP95} ms`;
	const problem = gateRow && !gateRow.error ? panWorkProblem(gateRow) : null;
	if (!gateRow) out.push({ name, status: 'FAIL', detail: 'not measured' });
	else if (gateRow.error) out.push({ name, status: 'FAIL', detail: `the row failed: ${gateRow.error}` });
	else if (!gateRow.panFrameMs || gateRow.panFrameMs.samples < GATE.minSamples || gateRow.panFrameMs.p95 === null) out.push({ name, status: 'FAIL', detail: `too few frames measured (${gateRow.panFrameMs ? gateRow.panFrameMs.samples : 0})` });
	else if (problem) out.push({ name, status: 'FAIL', detail: `frame intervals without drawing: ${problem}` });
	else out.push({ name, status: gateRow.panFrameMs.p95 <= GATE.maxP95 ? 'PASS' : 'FAIL', detail: `p95 ${gateRow.panFrameMs.p95} ms over ${gateRow.panFrameMs.samples} frames, ${gateRow.panWork.draws} drawn` });
	for (const row of rows) {
		const where = `${row.mode} ${row.n} at ${row.cpuThrottle}x`;
		const layout = row.neighbourLayout;
		if (layout && !LAYOUT_RAN.includes(layout.state)) out.push({ name: `the neighbour-graph layout runs (${where})`, status: 'FAIL', detail: `it ended ${layout.state}` });
		if (row.tsne && row.tsne.state !== 'done') out.push({ name: `the t-SNE layout runs (${where})`, status: 'FAIL', detail: `it ended ${row.tsne.state}` });
		if (layout && layout.state === 'done' && layout.overlap !== null && layout.pcaOverlap !== null) {
			out.push({ name: `neighbour layout shown only when it keeps at least PCA's neighbours (${where})`, status: layout.overlap >= layout.pcaOverlap ? 'PASS' : 'FAIL', detail: `overlap ${layout.overlap} vs PCA ${layout.pcaOverlap}${layout.timedOut ? ' (stopped at its time budget)' : ''}` });
		}
		out.push(privacyGate(row));
		for (const step of row.steps || []) out.push({ name: `${step.name} (${row.mode} ${row.n})`, status: step.status === 'PASS' ? 'PASS' : 'FAIL', detail: step.detail || '' });
	}
	return out;
}

/**
 * The privacy facts of one row's frames: B4's violations (L10's checker), the
 * dimension used, how many embed answers returned a query vector, and how many
 * requests carried exactly such a vector (so a row that queried shows the check
 * saw the vector go out).
 *
 * @param frames - [{dir: 'sent'|'received', msg}] in order (common.cjs captureFrames).
 * @param dimension - dialect.dimension, or null when unknown.
 * @param checker - common.cjs (privacyViolations, exchanges, fullVectors, sameVector).
 */
function privacySummary(frames, dimension, checker) {
	const embedded = [];
	if (Number.isInteger(dimension) && dimension > 0) {
		for (const x of checker.exchanges({ frames, sockets: 1 }, 'embed')) {
			const vectors = x.result && Array.isArray(x.result.vectors) ? x.result.vectors : [];
			for (const v of vectors) if (Array.isArray(v) && v.length === dimension) embedded.push(v);
		}
	}
	let vectorRequests = 0;
	for (const f of frames) {
		if (f.dir !== 'sent' || !f.msg || f.msg.type !== 'request' || !embedded.length) continue;
		const hits = checker.fullVectors(f.msg.arguments, dimension);
		if (hits.length && hits.every((h) => embedded.some((v) => checker.sameVector(v, h.vector)))) vectorRequests += 1;
	}
	return { frames: frames.length, dimension: Number.isInteger(dimension) ? dimension : null, embedAnswers: embedded.length, vectorRequests, violations: checker.privacyViolations(frames, dimension) };
}

// ---------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------

/** Open the connection document of a card (the drawer's open button, whatever its wording). */
async function openConnection(page, name) {
	await page.getByText(name).first().click();
	for (const label of [/^Open console$/i, /^Open documents$/i, /^Open$/i]) {
		const button = page.getByRole('button', { name: label }).first();
		if (await button.isVisible().catch(() => false)) {
			await button.click();
			return;
		}
	}
}

/** Click a view switch ("Map"): a tab, or a button where the header uses buttons. */
async function switchView(page, name) {
	const tab = page.getByRole('tab', { name }).first();
	if (await tab.isVisible().catch(() => false)) return tab.click();
	return page.getByRole('button', { name }).first().click();
}

/** Wait until the map shows a sample of `n` points in `mode` (n at most what the store holds). */
async function waitSample(page, n, mode, timeout) {
	await page.waitForFunction(
		({ n, mode }) => {
			const map = document.querySelector('.vector-map');
			const canvas = document.querySelector('[data-points]');
			if (!map || !canvas || map.getAttribute('data-map-state') !== 'ready' || map.getAttribute('data-sample-mode') !== mode) return false;
			return Number(canvas.getAttribute('data-points')) === n;
		},
		{ n, mode },
		{ timeout, polling: 100 },
	);
}

/** Run `action` while recording requestAnimationFrame intervals; the intervals (first two dropped). */
async function sampleFrames(page, action) {
	await page.evaluate(() => {
		window.__vxFrames = [];
		let last = performance.now();
		window.__vxSampling = true;
		const tick = (t) => {
			window.__vxFrames.push(t - last);
			last = t;
			if (window.__vxSampling) requestAnimationFrame(tick);
		};
		requestAnimationFrame(tick);
	});
	await action();
	return page.evaluate(() => {
		window.__vxSampling = false;
		return window.__vxFrames.slice(2);
	});
}

/** Drag across the canvas for about two seconds. */
async function pan(page, box) {
	const cx = box.x + box.width / 2;
	const cy = box.y + box.height / 2;
	await page.mouse.move(cx, cy);
	await page.mouse.down();
	for (let i = 0; i < 60; i += 1) {
		await page.mouse.move(cx + Math.sin(i / 6) * 220, cy + Math.cos(i / 6) * 120, { steps: 2 });
		await page.waitForTimeout(30);
	}
	await page.mouse.up();
}

/** Move the pointer across the canvas without a button (hover picking). */
async function hover(page, box) {
	for (let i = 0; i < 60; i += 1) {
		await page.mouse.move(box.x + box.width * (0.1 + 0.8 * (i / 59)), box.y + box.height * (0.5 + 0.3 * Math.sin(i / 5)), { steps: 2 });
		await page.waitForTimeout(30);
	}
}

/** Wheel in and out about the centre. */
async function zoom(page, box) {
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	for (let i = 0; i < 24; i += 1) {
		await page.mouse.wheel(0, i % 12 < 6 ? -120 : 120);
		await page.waitForTimeout(40);
	}
}

/** Choose a layout and wait for it to settle; its time, final state and overlaps. */
async function runLayout(page, layout, timeout = 120000) {
	const map = page.locator('.vector-map').first();
	const t0 = Date.now();
	await page.getByRole('combobox', { name: 'Layout' }).selectOption(layout);
	await page.waitForFunction((states) => states.includes(document.querySelector('.vector-map')?.getAttribute('data-layout-state') || ''), FINAL_LAYOUT_STATES, { timeout, polling: 100 });
	const state = await map.getAttribute('data-layout-state');
	const num = async (attr) => {
		const v = await map.getAttribute(attr);
		return v === null || v === '' ? null : Number(v);
	};
	const timedOut = (await page.getByText(/stopped at its time budget/).count()) > 0;
	const result = { layout, ms: Date.now() - t0, state, timedOut, overlap: await num('data-knn-overlap'), pcaOverlap: await num('data-pca-overlap') };
	await page.getByRole('combobox', { name: 'Layout' }).selectOption('pca');
	return result;
}

/** One step: PASS only on an explicit true. */
async function step(steps, name, fn) {
	try {
		const ok = await fn();
		steps.push({ name, status: ok === true ? 'PASS' : 'FAIL', detail: ok === true ? '' : JSON.stringify(ok) });
	} catch (e) {
		steps.push({ name, status: 'FAIL', detail: String(e && e.message ? e.message : e).split('\n')[0] });
	}
}

/** Find a screen position over a point: sweep the canvas until the tooltip shows. */
async function findPoint(page, box) {
	for (let gy = 0.15; gy < 0.9; gy += 0.05) {
		for (let gx = 0.1; gx < 0.92; gx += 0.04) {
			const x = box.x + box.width * gx;
			const y = box.y + box.height * gy;
			await page.mouse.move(x, y);
			if (await page.locator('[data-map-tooltip]').count()) return { x, y };
		}
	}
	return null;
}

/** The map's own steps (run once per size at 1x). */
async function mapSteps(page, box, row) {
	const steps = [];
	const map = page.locator('.vector-map').first();
	const points = Number(await page.locator('[data-points]').first().getAttribute('data-points'));
	let at = null;
	await step(steps, 'hover shows a tooltip', async () => {
		at = await findPoint(page, box);
		return at ? true : 'no tooltip anywhere on the canvas';
	});
	await step(steps, 'a click lists the 12 nearest chunks of the collection', async () => {
		if (!at) return 'no point found to click';
		await page.mouse.click(at.x, at.y);
		await page.getByRole('list', { name: 'Nearest chunks in the collection' }).first().waitFor({ timeout: 30000 });
		const items = await page.getByRole('list', { name: 'Nearest chunks in the collection' }).first().getByRole('listitem').count();
		return items === 12 ? true : `${items} neighbours listed`;
	});
	await step(steps, 'the keyboard path moves between points and Enter inspects', async () => {
		const canvas = page.locator('[data-points]').first();
		await canvas.focus();
		await page.keyboard.press('Escape');
		for (const key of ['ArrowRight', 'ArrowDown', 'ArrowLeft']) await page.keyboard.press(key);
		await page.keyboard.press('Enter');
		await page.getByRole('region', { name: 'Selected chunk' }).first().waitFor({ timeout: 15000 });
		return true;
	});
	await step(steps, 'the lasso selects points and says how many', async () => {
		await page.getByRole('button', { name: 'Lasso' }).click();
		const cx = box.x + box.width / 2;
		const cy = box.y + box.height / 2;
		await page.mouse.move(cx - 150, cy - 110);
		await page.mouse.down();
		for (const [dx, dy] of [[150, -110], [150, 110], [-150, 110], [-150, -110]]) await page.mouse.move(cx + dx, cy + dy, { steps: 8 });
		await page.mouse.up();
		const text = await page.getByRole('region', { name: 'Selected points' }).first().innerText({ timeout: 15000 });
		const m = /([\d,]+) points selected from ([\d,]+) documents/.exec(text);
		if (!m) return `no count in ${JSON.stringify(text.slice(0, 120))}`;
		const n = Number(m[1].replace(/,/g, ''));
		// The toggle stays pressed after a selection: turn it off for the steps that follow.
		await page.getByRole('button', { name: 'Lasso' }).click();
		return n > 0 && n <= points ? true : `${n} selected of ${points}`;
	});
	await step(steps, 'the Table alternative lists the points', async () => {
		await page.getByRole('button', { name: 'Table' }).click();
		const caption = await page.locator('caption').filter({ hasText: 'Points of the sample' }).count();
		const rows = await page.locator('table tbody tr').count();
		await page.getByRole('button', { name: 'Table' }).click();
		await page.locator('[data-points]').first().waitFor({ timeout: 15000 });
		return caption === 1 && rows === Math.min(100, points) ? true : `caption ${caption}, rows ${rows}`;
	});
	await step(steps, 'the legend says who computed the neighbour graph', async () => {
		const legend = page.getByRole('region', { name: 'Map legend' }).first();
		const source = await legend.getAttribute('data-knn-source');
		const text = await legend.innerText();
		if (source === 'native') return /neighbour graph computed by (Qdrant|[A-Z][\w ]+)/.test(text) ? true : 'native graph without its line';
		return /neighbour graph computed by the store node/.test(text) ? true : 'no neighbour-graph line';
	});
	if (row.n > 1000) {
		await step(steps, 't-SNE is refused above 1,000 points', async () => {
			// Read the option's own disabled property: Playwright's isDisabled() does not apply to an <option>.
			const disabled = await page
				.locator('select option[value="tsne"]')
				.first()
				.evaluate((option) => option.disabled);
			return disabled === true ? true : 'the t-SNE option is enabled';
		});
		await step(steps, 'Cancel stops a layout', async () => {
			await page.getByRole('combobox', { name: 'Layout' }).selectOption('neighbour-graph');
			await page.getByRole('button', { name: 'Cancel' }).click({ timeout: 10000 });
			await page.waitForFunction(() => document.querySelector('.vector-map')?.getAttribute('data-layout-state') === 'cancelled', null, { timeout: 15000 });
			return (await map.getAttribute('data-layout')) === 'pca' ? true : 'the cancelled layout is not back on PCA';
		});
	} else {
		await step(steps, QUERY_STEP, async () => {
			const box = page.getByRole('searchbox', { name: 'Query' }).first();
			if (await box.isDisabled()) return 'query disabled: the embedding node is not reachable from the Tools source';
			await box.fill(QUERY);
			await page.getByRole('button', { name: 'Run' }).click();
			// 'placed' comes with the projected star; the rays come with the search answer after it.
			await page.waitForFunction(
				() => {
					const root = document.querySelector('.vector-map');
					const state = root?.getAttribute('data-query-state') || '';
					return state === 'failed' || (state === 'placed' && Number(root.getAttribute('data-rays')) > 0);
				},
				null,
				{ timeout: 90000 }
			);
			const state = await map.getAttribute('data-query-state');
			const rays = Number(await map.getAttribute('data-rays'));
			return state === 'placed' && rays > 0 ? true : `query ${state}, ${rays} rays`;
		});
	}
	return steps;
}

// ---------------------------------------------------------------------------
// The lane
// ---------------------------------------------------------------------------

/**
 * The lane's arguments, in either of its two forms.
 *
 * Run directly: `<base-url> [out-json|out-dir] [sizes] [rates]`. From vector-ui:e2e-live:
 * `<base-url> <out-dir> <browser>`; the result then goes to <out-dir>/lane_vector_perf.json,
 * where the runner reads it.
 *
 * @param args - process.argv without the node binary and the script.
 * @param defaults - { base, outDir } when an argument is left out.
 */
function laneArgs(args, defaults) {
	const [base = defaults.base, target = defaults.outDir, third, fourth] = args;
	const out = target.endsWith('.json') ? path.dirname(target) : target;
	const outFile = target.endsWith('.json') ? target : path.join(out, 'lane_vector_perf.json');
	if (RUNNER_BROWSERS.includes(third)) return { base, outFile, browser: third, sizesArg: DEFAULT_SIZES, ratesArg: DEFAULT_RATES };
	return { base, outFile, browser: 'chrome', sizesArg: third || DEFAULT_SIZES, ratesArg: fourth || DEFAULT_RATES };
}

/** The result file: the measured rows, the gates, and the gates again as `results` rows for vector-ui:e2e-live. */
function resultOf(base, browserName, rows, gates) {
	const pass = gates.length > 0 && gates.every((g) => g.status === 'PASS');
	return { lane: 'vector-perf', fixture: PERF_FIXTURE, base, rows, gates, pass, results: gates.map((g) => ({ browser: browserName, run: 'perf', ...g })) };
}

async function main() {
	const E = require('../env.cjs');
	const C = require('./common.cjs');
	const { base, outFile, browser: browserName, sizesArg, ratesArg } = laneArgs(process.argv.slice(2), { base: E.ENGINE_URL, outDir: E.OUT_DIR });
	fs.mkdirSync(path.dirname(path.resolve(outFile)), { recursive: true });
	if (browserName !== 'chrome') {
		const refused = [{ name: 'lane', status: 'FAIL', detail: `the performance lane drives Google Chrome only, not ${browserName}` }];
		fs.writeFileSync(outFile, JSON.stringify(resultOf(base, browserName, [], refused), null, 1));
		return 1;
	}
	const sizes = parseSizes(sizesArg);
	const rates = String(ratesArg).split(',').map(Number).filter((r) => r > 0);
	const { chromium } = E.loadPlaywright();
	const browser = await chromium.launch({ channel: 'chrome', headless: true });
	// dialect.dimension from the store itself (not from the page), once.
	const store = C.storeClient(base);
	let dimension = null;
	let dimensionError = null;
	try {
		dimension = await store.dimension({ name: PERF_FIXTURE, projectId: PERF_PROJECT_ID });
	} catch (e) {
		dimensionError = String(e && e.message ? e.message : e).split('\n')[0];
	}
	const rows = [];
	for (const rate of rates) {
		for (const size of sizes) {
			const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
			const page = await context.newPage();
			const capture = C.captureFrames(page);
			const cdp = await context.newCDPSession(page);
			const row = { n: size.n, mode: size.mode, cpuThrottle: rate, browser: `Chrome ${browser.version()}`, fixture: PERF_FIXTURE };
			try {
				await E.signIn(page, base);
				await page.getByRole('button', { name: 'Open Vector Explorer' }).click();
				await page.getByText(PERF_FIXTURE).first().waitFor({ timeout: 60000 });
				await openConnection(page, PERF_FIXTURE);
				await switchView(page, /^Map$/);
				await page.locator('[data-points]').first().waitFor({ timeout: 180000 });
				await cdp.send('Emulation.setCPUThrottlingRate', { rate });
				const t0 = Date.now();
				const select = page.getByRole('combobox', { name: 'Points' });
				if ((await select.inputValue()) !== `${size.mode}:${size.n}`) await select.selectOption(`${size.mode}:${size.n}`);
				await waitSample(page, size.n, size.mode, 300000);
				row.timeToDrawMs = Date.now() - t0;
				const canvas = page.locator('[data-points]').first();
				row.pointsDrawn = Number(await canvas.getAttribute('data-points'));
				row.renderer = await canvas.getAttribute('data-renderer');
				await page.waitForTimeout(600);
				const box = await canvas.boundingBox();
				if (!box) throw new Error('the map canvas has no box');
				// What the pan really drew: frames drawn (data-draw-count) and the camera it moved (data-camera).
				const work = async () => ({ draws: await canvas.getAttribute('data-draw-count'), camera: await canvas.getAttribute('data-camera') });
				const before = await work();
				row.panFrameMs = summarise(await sampleFrames(page, () => pan(page, box)));
				const after = await work();
				row.panWork = { draws: before.draws === null || after.draws === null ? null : Number(after.draws) - Number(before.draws), cameraBefore: before.camera, cameraAfter: after.camera };
				row.hoverFrameMs = summarise(await sampleFrames(page, () => hover(page, box)));
				row.zoomFrameMs = summarise(await sampleFrames(page, () => zoom(page, box)));
				const draw = await canvas.getAttribute('data-draw-p95');
				row.drawP95Ms = draw === null ? null : Number(draw);
				row.neighbourLayout = await runLayout(page, 'neighbour-graph');
				if (size.n <= 1000) row.tsne = await runLayout(page, 'tsne');
				row.jsHeapMB = await page.evaluate(() => (performance.memory ? Math.round((performance.memory.usedJSHeapSize / 1048576) * 10) / 10 : null));
				if (rate === 1 && (size.n === 1000 || size.mode === 'light')) {
					await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
					row.steps = await mapSteps(page, box, row);
				}
				await page.screenshot({ path: outFile.replace(/\.json$/, `-${size.mode}-${size.n}-x${rate}.png`) });
			} catch (e) {
				row.error = String(e && e.message ? e.message : e).split('\n')[0];
				await page.screenshot({ path: outFile.replace(/\.json$/, `-${size.mode}-${size.n}-x${rate}-error.png`) }).catch(() => {});
			}
			row.privacy = { ...privacySummary(capture.frames, dimension, C), ...(dimensionError ? { dimensionError } : {}) };
			rows.push(row);
			console.log(JSON.stringify(row));
			await context.close();
		}
	}
	await browser.close();
	await store.close();
	const gates = evaluateGates(rows);
	for (const g of gates) console.log(`  [${g.status}] ${g.name}${g.detail ? ` -- ${g.detail}` : ''}`);
	const result = resultOf(base, browserName, rows, gates);
	fs.writeFileSync(outFile, JSON.stringify(result, null, 1));
	return result.pass ? 0 : 1;
}

module.exports = { GATE, PERF_PROJECT_ID, QUERY_STEP, pct, parseSizes, summarise, evaluateGates, privacySummary, laneArgs, resultOf };

if (require.main === module) {
	main().then(
		(code) => process.exit(code),
		(e) => {
			console.error(e);
			process.exit(2);
		},
	);
}
