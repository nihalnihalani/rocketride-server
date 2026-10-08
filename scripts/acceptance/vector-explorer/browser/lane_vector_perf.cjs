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
 * panning <= 33 ms. A check that measured nothing FAILS. The neighbour layout
 * may only be shown when it keeps at least as much of each neighbourhood as PCA.
 *
 * Fixture: gen_perf.py (a disposable collection of >= 6,000 chunks; its card is
 * VX_PERF_FIXTURE, default "vx-local Map performance (Qdrant)").
 *
 * Usage: node lane_vector_perf.cjs [base-url] [out-json] [sizes] [rates]
 *   sizes: comma list of n (detailed) or light:n   (default 500,1000,2000,light:5000)
 *   rates: comma list of CPU throttling rates       (default 1,4)
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
const QUERY = process.env.VX_PERF_QUERY || 'radio check-in schedule';
const FINAL_LAYOUT_STATES = ['done', 'kept-pca', 'cancelled', 'refused', 'failed', 'unavailable'];

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

/** PASS/FAIL rows from the measured rows. Nothing measured is a FAIL, never a pass. */
function evaluateGates(rows) {
	const out = [];
	const gateRow = rows.find((r) => r.n === GATE.n && r.mode === GATE.mode && r.cpuThrottle === GATE.rate);
	const name = `GATE ${GATE.n.toLocaleString('en-US')} ${GATE.mode} points at ${GATE.rate}x: pan p95 frame <= ${GATE.maxP95} ms`;
	if (!gateRow) out.push({ name, status: 'FAIL', detail: 'not measured' });
	else if (gateRow.error) out.push({ name, status: 'FAIL', detail: `the row failed: ${gateRow.error}` });
	else if (!gateRow.panFrameMs || gateRow.panFrameMs.samples < GATE.minSamples || gateRow.panFrameMs.p95 === null) out.push({ name, status: 'FAIL', detail: `too few frames measured (${gateRow.panFrameMs ? gateRow.panFrameMs.samples : 0})` });
	else out.push({ name, status: gateRow.panFrameMs.p95 <= GATE.maxP95 ? 'PASS' : 'FAIL', detail: `p95 ${gateRow.panFrameMs.p95} ms over ${gateRow.panFrameMs.samples} frames` });
	for (const row of rows) {
		const layout = row.neighbourLayout;
		if (layout && layout.state === 'done' && layout.overlap !== null && layout.pcaOverlap !== null) {
			out.push({ name: `neighbour layout shown only when it keeps at least PCA's neighbours (${row.mode} ${row.n} at ${row.cpuThrottle}x)`, status: layout.overlap >= layout.pcaOverlap ? 'PASS' : 'FAIL', detail: `overlap ${layout.overlap} vs PCA ${layout.pcaOverlap}` });
		}
		for (const step of row.steps || []) out.push({ name: `${step.name} (${row.mode} ${row.n})`, status: step.status === 'PASS' ? 'PASS' : 'FAIL', detail: step.detail || '' });
	}
	return out;
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
	const result = { layout, ms: Date.now() - t0, state, overlap: await num('data-knn-overlap'), pcaOverlap: await num('data-pca-overlap') };
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
			const disabled = await page.locator('select option[value="tsne"]').first().isDisabled();
			return disabled ? true : 'the t-SNE option is enabled';
		});
		await step(steps, 'Cancel stops a layout', async () => {
			await page.getByRole('combobox', { name: 'Layout' }).selectOption('neighbour-graph');
			await page.getByRole('button', { name: 'Cancel' }).click({ timeout: 10000 });
			await page.waitForFunction(() => document.querySelector('.vector-map')?.getAttribute('data-layout-state') === 'cancelled', null, { timeout: 15000 });
			return (await map.getAttribute('data-layout')) === 'pca' ? true : 'the cancelled layout is not back on PCA';
		});
	} else {
		await step(steps, 'a text query draws its star and rays (when the embedding node answers)', async () => {
			const box = page.getByRole('searchbox', { name: 'Query' }).first();
			if (await box.isDisabled()) return 'query disabled: the embedding node is not reachable from the Tools source';
			await box.fill(QUERY);
			await page.getByRole('button', { name: 'Run' }).click();
			await page.waitForFunction(() => ['placed', 'failed'].includes(document.querySelector('.vector-map')?.getAttribute('data-query-state') || ''), null, { timeout: 90000 });
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

async function main() {
	const E = require('../env.cjs');
	const [, , base = E.ENGINE_URL, outFile = path.join(E.OUT_DIR, 'lane_vector_perf.json'), sizesArg = DEFAULT_SIZES, ratesArg = DEFAULT_RATES] = process.argv;
	const sizes = parseSizes(sizesArg);
	const rates = String(ratesArg).split(',').map(Number).filter((r) => r > 0);
	fs.mkdirSync(path.dirname(path.resolve(outFile)), { recursive: true });
	const { chromium } = E.loadPlaywright();
	const browser = await chromium.launch({ channel: 'chrome', headless: true });
	const rows = [];
	for (const rate of rates) {
		for (const size of sizes) {
			const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
			const page = await context.newPage();
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
				row.panFrameMs = summarise(await sampleFrames(page, () => pan(page, box)));
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
			rows.push(row);
			console.log(JSON.stringify(row));
			await context.close();
		}
	}
	await browser.close();
	const gates = evaluateGates(rows);
	for (const g of gates) console.log(`  [${g.status}] ${g.name}${g.detail ? ` -- ${g.detail}` : ''}`);
	const pass = gates.every((g) => g.status === 'PASS');
	fs.writeFileSync(outFile, JSON.stringify({ lane: 'vector-perf', fixture: PERF_FIXTURE, base, rows, gates, pass }, null, 1));
	return pass ? 0 : 1;
}

module.exports = { GATE, pct, parseSizes, summarise, evaluateGates };

if (require.main === module) {
	main().then(
		(code) => process.exit(code),
		(e) => {
			console.error(e);
			process.exit(2);
		},
	);
}
