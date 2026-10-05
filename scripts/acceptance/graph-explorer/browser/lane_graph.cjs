// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Browser lane (production shell served by the real engine): Graph Explorer.
 * Chrome (installed) / Firefox / WebKit (Playwright builds), fresh context each.
 * Fixtures: start_fixtures.py (tools-only AGE / Neo4j / FalkorDB pipelines on the
 * acceptance graphs, allow_execute off). Every step records PASS/FAIL and a screenshot.
 * Usage: node lane_graph.cjs [base-url] [out-dir] [chrome|firefox|webkit|all] [age,neo4j,falkordb]
 * (base-url and out-dir default to ENGINE_URL and OUT_DIR).
 * Browsers: Chrome lanes use the installed Google Chrome (channel "chrome"); Firefox and
 * WebKit use Playwright builds (`npx playwright install firefox webkit`, optionally under
 * PLAYWRIGHT_BROWSERS_PATH).
 */
'use strict';
const E = require('../env.cjs');
const { chromium, firefox, webkit } = E.loadPlaywright();
const fs = require('fs');
const path = require('path');

const [, , base = E.ENGINE_URL, out = E.OUT_DIR, which = 'all', enginesArg = 'neo4j,falkordb,age'] = process.argv;
const ENGINES = { age: E.FIXTURES.age, neo4j: E.FIXTURES.neo4j, falkordb: E.FIXTURES.falkordb };
const results = [];
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';

function rec(browser, engine, name, ok, detail) {
	results.push({ browser, engine, name, status: ok ? 'PASS' : 'FAIL', detail });
	console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${browser}/${engine}: ${name}${!ok && detail ? ` -- ${String(detail).slice(0, 220)}` : ''}`);
}

async function step(ctx, name, fn) {
	try {
		const detail = await fn();
		rec(ctx.browser, ctx.engine, name, detail !== false, detail === false ? 'returned false' : undefined);
	} catch (e) {
		rec(ctx.browser, ctx.engine, name, false, e.message.split('\n')[0]);
	}
	await ctx.page.screenshot({ path: path.join(out, `graph-${ctx.browser}-${ctx.engine}-${name.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)}.png`) }).catch(() => {});
}

async function typeAndRun(page, text) {
	const editor = page.locator('.monaco-editor .view-lines').first();
	if (await editor.isVisible().catch(() => false)) {
		await editor.click();
		await page.keyboard.press(`${MOD}+a`);
		await page.keyboard.press('Delete');
		await page.keyboard.type(text);
	} else {
		const ta = page.getByRole('textbox').first();
		await ta.fill(text);
	}
	await page.keyboard.press(`${MOD}+Enter`);
}

async function runEngine(browserName, launcher, opts, engine) {
	const browser = await launcher.launch(opts);
	const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
	const page = await context.newPage();
	const errors = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	const ctx = { browser: browserName, engine, page };
	try {
		await E.signIn(page, base);
		await step(ctx, 'open Graph Explorer, connections listed', async () => {
			await page.getByRole('button', { name: 'Open Graph Explorer' }).click();
			await page.getByText(ENGINES[engine]).first().waitFor({ timeout: 45000 });
			const body = await page.locator('body').innerText();
			return Object.values(ENGINES).every((n) => body.includes(n)) && !/db_postgres|db_supabase/.test(body);
		});
		await step(ctx, 'drawer shows engine identity and opens the workbench', async () => {
			await page.getByText(ENGINES[engine]).first().click();
			await page.getByRole('button', { name: 'Open workbench' }).waitFor({ timeout: 30000 });
			const drawer = await page.locator('body').innerText();
			const ok = /neo4j|falkordb|age|apache/i.test(drawer);
			await page.getByRole('button', { name: 'Open workbench' }).click();
			await page.locator('.monaco-editor .view-lines, textarea').first().waitFor({ timeout: 45000 });
			return ok;
		});
		await step(ctx, 'Cmd/Ctrl+Enter path query draws nodes on the canvas', async () => {
			await typeAndRun(page, "MATCH p = (a:Person {name: 'Ada GX'})-[:KNOWS*2]->(c) RETURN p");
			await page.locator('.react-flow__node').nth(2).waitFor({ timeout: 60000 });
			return (await page.locator('.react-flow__node').count()) >= 3;
		});
		await step(ctx, 'Table tab shows the path row', async () => {
			await page.getByRole('tab', { name: 'Table' }).click();
			await page.waitForTimeout(500);
			return /Ada GX|path|Charles GX/i.test(await page.locator('body').innerText());
		});
		await step(ctx, 'Raw tab shows tagged JSON', async () => {
			await page.getByRole('tab', { name: 'Raw' }).click();
			await page.waitForTimeout(500);
			return (await page.locator('body').innerText()).includes('@kind');
		});
		await step(ctx, 'inspector opens on a node with labels and Copy JSON', async () => {
			await page.getByRole('tab', { name: 'Graph' }).click();
			await page.locator('.react-flow__node').first().waitFor({ timeout: 20000 });
			// A click selects (toolbar shows "Focused: …"); Inspect (or Enter) opens the inspector.
			await page.locator('.react-flow__node').first().click();
			await page.getByRole('button', { name: 'Inspect' }).first().click();
			await page.getByRole('button', { name: 'Copy JSON' }).first().waitFor({ timeout: 15000 });
			await page.waitForTimeout(700); // drawer slide-in
			const text = await page.locator('body').innerText();
			const ok = /identity/i.test(text) && /labels/i.test(text) && /propert/i.test(text);
			await page.screenshot({ path: path.join(out, `graph-${ctx.browser}-${ctx.engine}-inspector-open.png`) });
			return ok;
		});
		await step(ctx, 'Escape closes the inspector (modal dialog)', async () => {
			await page.keyboard.press('Escape');
			await page.waitForTimeout(900);
			const open = await page.locator('[role="dialog"][aria-modal="true"]').count();
			if (open > 0) {
				// Close it with its Close button so the rest of the lane can continue.
				await page.getByRole('button', { name: 'Close' }).last().click();
				await page.waitForTimeout(900);
				return false;
			}
			return true;
		});
		await step(ctx, 'Expand runs and reports an outcome', async () => {
			const before = await page.locator('.react-flow__node').count();
			await page.getByRole('button', { name: 'Expand' }).first().click();
			await page.waitForTimeout(4000);
			const after = await page.locator('.react-flow__node').count();
			const text = await page.locator('body').innerText();
			return after >= before && /neighbour|added|No new/i.test(text);
		});
		await step(ctx, 'schema Refresh reports freshness', async () => {
			await page.getByRole('button', { name: 'Refresh' }).first().click();
			await page.getByText(/refreshed|just now/i).first().waitFor({ timeout: 90000 });
			return true;
		});
		await step(ctx, 'History lists the statement', async () => {
			await page.getByRole('button', { name: 'History' }).first().click();
			await page.waitForTimeout(1000);
			return (await page.locator('body').innerText()).includes("name: 'Ada GX'");
		});
		await step(ctx, 'browse editor refuses a write with the text-check sentence', async () => {
			await page.keyboard.press('Escape');
			await typeAndRun(page, 'CREATE (:Intruder {x: 1})');
			await page.getByText(/text check, not a database safeguard/i).first().waitFor({ timeout: 20000 });
			return true;
		});
		await step(ctx, 'Ask without an LLM shows an unavailable note, not an error', async () => {
			const ask = page.getByLabel('Ask a question about this graph');
			if (!(await ask.isVisible().catch(() => false))) return 'ask bar not visible';
			await ask.fill('who knows Ada?');
			await ask.press('Enter');
			await page.waitForTimeout(6000);
			const text = await page.locator('body').innerText();
			return /unavailable|language model|LLM/i.test(text);
		});
		rec(browserName, engine, 'no uncaught page errors', errors.length === 0, errors.join(' | '));
	} catch (e) {
		rec(browserName, engine, 'lane completed', false, e.message.split('\n')[0]);
	} finally {
		await browser.close();
	}
}

(async () => {
	fs.mkdirSync(out, { recursive: true });
	const lanes = { chrome: [chromium, { channel: 'chrome' }], firefox: [firefox, {}], webkit: [webkit, {}] };
	for (const [name, [launcher, opts]] of Object.entries(lanes)) {
		if (which !== 'all' && which !== name) continue;
		for (const engine of enginesArg.split(',')) {
			console.log(`== ${name} / ${engine}`);
			await runEngine(name, launcher, opts, engine);
		}
	}
	fs.writeFileSync(path.join(out, 'lane_graph.json'), JSON.stringify(results, null, 1));
	const failed = results.filter((r) => r.status !== 'PASS').length;
	console.log(`== ${results.length - failed} passed, ${failed} failed`);
	process.exit(failed ? 1 : 0);
})();
