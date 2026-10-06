// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Browser lane (production shell served by the real engine): SQL Explorer.
 * Runs in Chrome (installed), Firefox and WebKit (Playwright builds). Each run
 * uses a fresh browser context, so no cached remote can mask the served build.
 * Fixtures: start_fixtures.py (its SQL table SQL_TABLE, default gx_items, holds 'item 1'..'item 25').
 * Usage: node lane_sql.cjs [base-url] [out-dir] [chrome|firefox|webkit|all]
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

const [, , base = E.ENGINE_URL, out = E.OUT_DIR, which = 'all'] = process.argv;
const SQL_TABLE = process.env.SQL_TABLE || 'gx_items';
const results = [];
const rec = (browser, name, ok, detail) => {
	results.push({ browser, name, status: ok ? 'PASS' : 'FAIL', detail });
	console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${browser}: ${name}${!ok && detail ? ` -- ${String(detail).slice(0, 200)}` : ''}`);
};

const signIn = (page) => E.signIn(page, base);

async function runLane(name, launcher, opts) {
	const browser = await launcher.launch(opts);
	const version = browser.version();
	const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
	const page = await context.newPage();
	const errors = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	try {
		await signIn(page);
		rec(name, `signed in (${version})`, true);
		await page.getByRole('button', { name: 'Open SQL Explorer' }).click();
		await page.getByRole('heading', { name: 'Connections' }).waitFor({ timeout: 30000 });
		await page.getByText('Running').first().waitFor({ timeout: 30000 });
		await page.waitForTimeout(1500);
		const body = await page.locator('body').innerText();
		rec(name, 'lists db_supabase', body.includes('db_supabase'), body.slice(0, 300));
		rec(name, 'lists rocketride_sql', body.includes('rocketride_sql'));
		rec(name, 'does not list graph nodes', !/graph_neo4j|graph_falkordb|rocketride_graph/.test(body));
		await page.screenshot({ path: path.join(out, `sql-${name}-connections.png`) });

		// Edit/Delete reachable by accessibility (shell ConnectionCard fix): the card's
		// button semantics no longer hide its own actions.
		const snap = await page.locator('body').ariaSnapshot();
		rec(name, 'connection cards expose button roles', /button/.test(snap));

		// Open the write-enabled connection and run a read through the shared runner.
		await page.getByText(E.FIXTURES.sqlWrite).first().click();
		await page.getByRole('button', { name: 'New Query' }).click();
		// Monaco loads from its CDN; click its visible view, not the hidden input.
		const editor = page.locator('.monaco-editor .view-lines').first();
		await editor.waitFor({ state: 'visible', timeout: 45000 });
		await editor.click();
		await page.keyboard.type(`select name, qty from ${SQL_TABLE} where qty > 22 order by qty`);
		await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Enter' : 'Control+Enter');
		await page.getByText('item 25').first().waitFor({ timeout: 30000 });
		const res = await page.locator('body').innerText();
		rec(name, 'runner shows result rows', ['item 23', 'item 24', 'item 25'].every((x) => res.includes(x)));
		await page.screenshot({ path: path.join(out, `sql-${name}-result.png`) });
		rec(name, 'no uncaught page errors', errors.length === 0, errors.join(' | '));
	} catch (e) {
		rec(name, 'lane completed', false, e.message);
		await page.screenshot({ path: path.join(out, `sql-${name}-failure.png`) }).catch(() => {});
	} finally {
		await browser.close();
	}
}

(async () => {
	fs.mkdirSync(out, { recursive: true });
	const lanes = {
		chrome: [chromium, { channel: 'chrome' }],
		firefox: [firefox, {}],
		webkit: [webkit, {}],
	};
	for (const [name, [launcher, opts]] of Object.entries(lanes)) {
		if (which !== 'all' && which !== name) continue;
		console.log(`== ${name}`);
		await runLane(name, launcher, opts);
	}
	fs.writeFileSync(path.join(out, 'lane_sql.json'), JSON.stringify(results, null, 1));
	const failed = results.filter((r) => r.status !== 'PASS').length;
	console.log(`== ${results.length - failed} passed, ${failed} failed`);
	process.exit(failed ? 1 : 0);
})();
