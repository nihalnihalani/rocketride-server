// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Editor line-number colours in both RocketRide themes, SQL Explorer and Graph Explorer, served shell.
 * Monaco reads a non-hex theme colour as red: any rgb(255, 0, 0) line number is the F9 bug.
 * Fixtures: start_fixtures.py. THEMES (light,dark) and APPS (sql,graph) narrow the runs.
 * Usage: node probe_linenumbers.cjs [base-url] [out-dir] [chrome|firefox|webkit|all]
 * (base-url and out-dir default to ENGINE_URL and OUT_DIR).
 * Browsers: Chrome lanes use the installed Google Chrome (channel "chrome"); Firefox and
 * WebKit use Playwright builds (`npx playwright install firefox webkit`, optionally under
 * PLAYWRIGHT_BROWSERS_PATH).
 */
'use strict';
// page.evaluate() and addInitScript() callbacks run in the browser.
/* global document, getComputedStyle */
const E = require('../env.cjs');
const { chromium, firefox, webkit } = E.loadPlaywright();
const fs = require('fs');
const path = require('path');

const [, , base = E.ENGINE_URL, out = E.OUT_DIR, which = 'all'] = process.argv;
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
const results = [];
const rec = (b, name, ok, detail) => {
	results.push({ browser: b, name, status: ok ? 'PASS' : 'FAIL', detail });
	console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${b}: ${name}${detail !== undefined ? ` -- ${JSON.stringify(detail).slice(0, 240)}` : ''}`);
};
const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return +((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2); };
const nums = (s) => (/rgba?\(([^)]+)\)/.exec(s) || ['', '0,0,0'])[1].split(/[\s,]+/).map(Number);

async function lineNumbers(page) {
	return page.evaluate(() => {
		const ed = [...document.querySelectorAll('.monaco-editor')].find((e) => e.getBoundingClientRect().width > 0);
		if (!ed) return null;
		const bg = getComputedStyle(ed.querySelector('.margin') || ed).backgroundColor;
		return { bg, numbers: [...ed.querySelectorAll('.line-numbers')].map((e) => ({ text: e.textContent.trim(), color: getComputedStyle(e).color, active: e.classList.contains('active-line-number') })) };
	});
}

async function twoLines(page, a, b) {
	const editor = page.locator('.monaco-editor .view-lines').filter({ visible: true }).first();
	await editor.waitFor({ state: 'visible', timeout: 45000 });
	await editor.click();
	await page.keyboard.press(`${MOD}+a`);
	await page.keyboard.press('Delete');
	await page.keyboard.type(a);
	await page.keyboard.press('Enter');
	await page.keyboard.type(b);
	await page.waitForTimeout(400);
}

async function run(bname, launcher, opts, theme, app) {
	const browser = await launcher.launch(opts);
	const page = await (await browser.newContext({ viewport: { width: 1440, height: 920 } })).newPage();
	const want = theme === 'dark' ? 'dark' : 'light';
	try {
		await E.signIn(page, base);
		const mode = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--rr-palette-mode').replace(/['"]/g, '').trim());
		if ((await mode()) !== want) {
			await page.getByRole('switch', { name: want === 'dark' ? 'Switch to dark mode' : 'Switch to light mode' }).click();
			await page.waitForTimeout(1200);
		}
		const tag = `${theme}`;
		// The shell may reopen the last app after sign-in; start every run from the home page.
		const opener = page.getByRole('button', { name: app === 'sql' ? 'Open SQL Explorer' : 'Open Graph Explorer' });
		if (!(await opener.isVisible({ timeout: 4000 }).catch(() => false))) {
			await page.getByRole('button', { name: 'Go to home' }).first().click().catch(() => {});
			await opener.waitFor({ timeout: 15000 });
		}
		if (app === 'sql') {
			await page.getByRole('button', { name: 'Open SQL Explorer' }).click();
			await page.getByText(E.FIXTURES.sqlWrite).first().click();
			await page.getByRole('button', { name: 'New Query' }).click();
			await twoLines(page, 'select 1', 'from generate_series(1, 2)');
			const sql = await lineNumbers(page);
			await page.screenshot({ path: path.join(out, `ln-${bname}-${tag}-sql.png`) });
			checkNums(bname, `SQL Explorer ${tag}`, sql);
		} else {
			await page.getByRole('button', { name: 'Open Graph Explorer' }).click();
			await page.getByText(E.FIXTURES.falkordb).first().click();
			await page.getByRole('button', { name: 'Open workbench' }).click();
			await twoLines(page, 'MATCH (n)', 'RETURN n LIMIT 5');
			const graph = await lineNumbers(page);
			await page.screenshot({ path: path.join(out, `ln-${bname}-${tag}-graph.png`) });
			checkNums(bname, `Graph Explorer ${tag}`, graph);
		}
	} catch (e) {
		rec(bname, `${app} ${theme} lane completed`, false, e.message.split('\n')[0]);
		await page.screenshot({ path: path.join(out, `ln-${bname}-${theme}-${app}-error.png`) }).catch(() => {});
	}
	await browser.close();
}

function checkNums(bname, label, info) {
	if (!info || info.numbers.length < 2) return rec(bname, `${label}: two line numbers drawn`, false, info);
	const bg = nums(info.bg);
	for (const n of info.numbers) {
		const c = nums(n.color);
		const r = ratio(c, bg);
		rec(bname, `${label}: line ${n.text}${n.active ? ' (active)' : ''} ${n.color} = ${r}:1, not red, >= 4.5`, !/^rgb\(255, 0, 0\)$/.test(n.color) && r >= 4.5, { color: n.color, bg: info.bg, ratio: r });
	}
}

(async () => {
	fs.mkdirSync(out, { recursive: true });
	const all = { chrome: [chromium, { channel: 'chrome' }], firefox: [firefox, {}], webkit: [webkit, {}] };
	for (const b of which === 'all' ? Object.keys(all) : which.split(',')) {
		for (const theme of (process.env.THEMES || 'light,dark').split(',')) for (const app of (process.env.APPS || 'sql,graph').split(',')) await run(b, all[b][0], all[b][1], theme, app);
	}
	fs.writeFileSync(path.join(out, 'probe_linenumbers.json'), JSON.stringify(results, null, 1));
	const pass = results.filter((r) => r.status === 'PASS').length;
	console.log(`\n${pass}/${results.length} PASS`);
	process.exit(pass === results.length ? 0 : 1);
})();
