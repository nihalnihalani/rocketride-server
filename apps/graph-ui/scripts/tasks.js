// MIT License
//
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

/**
 * Graph UI Build Module
 *
 * Graph database workbench - browse, query and visualise Apache AGE, Neo4j and
 * FalkorDB graphs reached through pipeline graph tool nodes.
 */
const path = require('path');
const { existsSync } = require('node:fs');
const { readdir } = require('node:fs/promises');
const { createAppModule } = require('../../../scripts/lib/appModule');
const { execCommand } = require('../../../scripts/lib');

const APP_ROOT = path.join(__dirname, '..');
const TESTS_DIR = path.join(APP_ROOT, 'tests');
const ACCEPTANCE_DIR = path.join(APP_ROOT, '..', '..', 'scripts', 'acceptance', 'graph-explorer');
const ACCEPTANCE_BROWSER_DIR = path.join(ACCEPTANCE_DIR, 'browser');

// Suites that must exist for the gate to mean anything. A missing file here is
// a broken checkout or a deleted suite, not an app "without tests", so the
// gate fails instead of running whatever happens to be left.
const REQUIRED_TESTS = ['scaffold.test.ts', 'lexer.test.ts', 'split.test.ts', 'classify.test.ts', 'quote.test.ts', 'graph.values.test.ts', 'graph.model.test.ts', 'graph.geometry.test.ts', 'layout.core.test.ts', 'layout.client.test.ts', 'recipes.test.ts', 'flowProps.test.ts', 'graph.colors.test.ts', 'graph.keynav-schema.test.ts', 'graph.fixtures.test.ts', 'graph.wording.test.ts', 'graph.dialect.test.ts', 'adapter.test.ts', 'graph.connections.test.ts', 'graph.inspector-ask.test.ts', 'graph.run-failures.test.ts', 'graph.addresses-schema.test.ts', 'cypher.targets.test.ts', 'graph.session.test.ts', 'graph.writeconfirm.test.ts', 'adapter.actions.test.ts', 'graph.schematree.test.ts', 'graph.live-fixtures.test.ts', 'templates.test.ts', 'graph.identity.test.ts', 'graph.wiring.test.ts', 'canvas.stable.test.ts', 'canvas.fit.test.ts', 'a11y.contrast.test.ts', 'graph.surface.test.ts', 'graph.identity-change.test.ts', 'builder.e2e.test.ts'];

const mod = createAppModule({
	name: 'graph-ui',
	description: 'Graph Explorer Application',
	appRoot: APP_ROOT,
	dev: true,
});

// graph-ui:test - runs node:test (via tsx) over tests/*.test.ts(x) after a
// typecheck of src/ and tests/. The tested modules are pure logic and reach the
// platform through `import type` alone (erased by tsx); stub-shell.cjs stands in
// for the few value imports (see its header). Runs under test targets, never as
// a build step (a normal build must not stream test output).
mod.actions.push({
	name: 'graph-ui:test',
	action: () => ({
		description: 'Test graph-ui',
		run: async (_ctx, task) => {
			// Fail rather than pass silently: tests/ is tracked source, so an
			// absent directory or a pattern that stops matching is a broken
			// checkout, and `builder test` runs this action in CI, where
			// returning cleanly would report the suite green with nothing run.
			if (!existsSync(TESTS_DIR)) {
				throw new Error(`No tests/ directory at ${TESTS_DIR} - graph-ui's suite is tracked source and must be present`);
			}
			// `recursive` is ignored on Node 20.0.0 exactly (it landed in 20.1.0), so
			// tests/ stays flat (fixtures and helpers live in subdirectories and are
			// not test files).
			const testFiles = (await readdir(TESTS_DIR)).filter((f) => f.endsWith('.test.ts') || f.endsWith('.test.tsx')).map((f) => path.join('tests', f));
			if (testFiles.length === 0) {
				throw new Error('No graph-ui test files found under tests/ - expected at least one *.test.ts(x)');
			}
			const missing = REQUIRED_TESTS.filter((f) => !testFiles.includes(path.join('tests', f)));
			if (missing.length > 0) {
				throw new Error(`graph-ui required test files are missing: ${missing.join(', ')}`);
			}
			// tsx erases types rather than checking them, so the tests would
			// otherwise run under no typechecker at all. tsconfig.test.json is the
			// second program that covers tests/ as well as src/.
			//
			// It re-checks src/** too, so this step assumes a built shell: on a fresh
			// clone .rocketride/shell/shell.tgz is the bootstrap stub until
			// shell:build replaces it (see scripts/lib/appModule.js). Build before
			// testing locally.
			await execCommand('npx', ['tsc', '-p', 'tsconfig.test.json', '--noEmit'], { task, cwd: APP_ROOT });
			// './' prefix required: a bare relative path in --require resolves as a
			// package name, not a file.
			await execCommand('node', ['--require', './scripts/stub-shell.cjs', '--import', 'tsx', '--test', '--test-reporter=spec', ...testFiles], { task, cwd: APP_ROOT });
		},
	}),
});

// =============================================================================
// graph-ui:e2e - the committed Playwright lanes, OPT-IN
// =============================================================================
//
// Runs the pass/fail browser lanes in scripts/acceptance/graph-explorer/browser
// (see that folder's README for the engine, fixtures and containers they need)
// against the engine named by ENGINE_URL. It is deliberately NOT part of
// graph-ui:test, `builder test` or CI: it needs a running engine serving the
// built apps, the fixture pipelines, the database containers, Playwright and
// the browsers. What it checks first, and fails on with a sentence saying what
// is missing: the URL, the engine answering it, Playwright, and every chosen
// browser starting. Then every chosen lane runs once per browser (each into
// its own results folder) and the action fails if any lane run failed.
//
//   ENGINE_URL              required: the engine under test (http or https)
//   GRAPH_UI_E2E_BROWSERS   chrome (default) | firefox | webkit | all, or a comma list
//   GRAPH_UI_E2E_LANES      graph,sql,a11y,linenumbers (default: all four), or a subset
//   GRAPH_UI_E2E_ENGINES    graph lane only: age,neo4j,falkordb (default: all three)
//   OUT_DIR                 results (default: the acceptance folder's git-ignored out/e2e)
//   PLAYWRIGHT_DIR, PLAYWRIGHT_BROWSERS_PATH   as in the acceptance README
//
// lane_a11y measures the shell's own text too, and some shell theme pairs are
// below 4.5:1 today (see the acceptance README), so its contrast rows can fail
// on text Graph Explorer does not colour. Read lane_a11y.json before filing one.

/** The pass/fail lanes, by the name GRAPH_UI_E2E_LANES uses (lane_perf reports measurements and is not one). */
const LANES = { graph: 'lane_graph.cjs', sql: 'lane_sql.cjs', a11y: 'lane_a11y.cjs', linenumbers: 'probe_linenumbers.cjs' };
const BROWSERS = ['chrome', 'firefox', 'webkit'];
const GRAPH_ENGINES = ['age', 'neo4j', 'falkordb'];
const RECIPE = 'scripts/acceptance/graph-explorer/README.md';

/**
 * Split a comma list and check every entry against the allowed names.
 *
 * @param {string} value - The list.
 * @param {string[]} allowed - The names it may hold.
 * @param {string} what - What an entry is, for the error.
 * @returns {string[]} The entries, in the order given.
 */
function listOf(value, allowed, what) {
	const items = value
		.split(',')
		.map((item) => item.trim())
		.filter(Boolean);
	for (const item of items) {
		if (!allowed.includes(item)) throw new Error(`Unknown ${what} "${item}": use ${allowed.join(', ')}.`);
	}
	if (items.length === 0) throw new Error(`No ${what} given: use ${allowed.join(', ')}.`);
	return items;
}

/**
 * Read graph-ui:e2e's settings from the environment.
 *
 * @param {Record<string, string | undefined>} env - The environment.
 * @returns {{ url: string, browsers: string[], lanes: { name: string, script: string }[], outDir: string, engines: string | null }} The plan.
 */
function planE2e(env) {
	const raw = (env.ENGINE_URL || '').trim();
	if (!raw) {
		throw new Error(`graph-ui:e2e needs ENGINE_URL: the URL of a running engine that serves the built apps, with the fixture pipelines started. The recipe is in ${RECIPE}.`);
	}
	let parsed;
	try {
		parsed = new URL(raw);
	} catch {
		parsed = null;
	}
	if (!parsed || (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')) {
		throw new Error(`ENGINE_URL must be an http(s) URL, for example http://127.0.0.1:5580 (got "${raw}").`);
	}
	const chosen = listOf(env.GRAPH_UI_E2E_BROWSERS || 'chrome', [...BROWSERS, 'all'], 'browser');
	const browsers = chosen.includes('all') ? [...BROWSERS] : chosen;
	const lanes = listOf(env.GRAPH_UI_E2E_LANES || Object.keys(LANES).join(','), Object.keys(LANES), 'lane').map((name) => ({ name, script: LANES[name] }));
	const engines = env.GRAPH_UI_E2E_ENGINES ? listOf(env.GRAPH_UI_E2E_ENGINES, GRAPH_ENGINES, 'graph engine').join(',') : null;
	return { url: raw.replace(/\/+$/, ''), browsers, lanes, outDir: env.OUT_DIR || path.join(ACCEPTANCE_DIR, 'out', 'e2e'), engines };
}

/**
 * Load Playwright where the lanes load it (env.cjs): PLAYWRIGHT_DIR, else the acceptance browser folder.
 *
 * @param {Record<string, string | undefined>} env - The environment.
 * @returns {object} The Playwright module.
 */
function loadAcceptancePlaywright(env) {
	const root = env.PLAYWRIGHT_DIR || ACCEPTANCE_BROWSER_DIR;
	return require(path.join(root, 'node_modules', 'playwright'));
}

/**
 * Check, before any lane runs, that the engine answers, Playwright loads and every chosen browser starts.
 *
 * @param {ReturnType<typeof planE2e>} plan - The plan.
 * @param {{ fetch: Function, loadPlaywright: Function }} deps - The network and Playwright (tests pass stand-ins).
 * @returns {Promise<void>} Resolves when everything is there; rejects with what is missing.
 */
async function preflightE2e(plan, deps) {
	let answer;
	try {
		answer = await deps.fetch(`${plan.url}/`, { signal: AbortSignal.timeout(10000) });
	} catch (error) {
		const cause = error && error.cause && error.cause.message ? error.cause.message : error && error.message ? error.message : String(error);
		throw new Error(`No engine answered at ${plan.url} (${cause}). Start one that serves the built apps (${RECIPE}, "Fake broker and engine"), or set ENGINE_URL to it.`);
	}
	if (!answer.ok) throw new Error(`The engine at ${plan.url} answered HTTP ${answer.status} for its start page, so the lanes cannot open the apps.`);

	let playwright;
	try {
		playwright = deps.loadPlaywright();
	} catch (error) {
		throw new Error(`Playwright is not installed for the lanes (${String(error && error.message).split('\n')[0]}). Run \`npm install --no-package-lock\` in scripts/acceptance/graph-explorer/browser, or set PLAYWRIGHT_DIR to a folder whose node_modules has it.`);
	}
	const launchers = { chrome: [playwright.chromium, { channel: 'chrome' }], firefox: [playwright.firefox, {}], webkit: [playwright.webkit, {}] };
	const failed = [];
	for (const name of plan.browsers) {
		const [launcher, options] = launchers[name];
		try {
			const browser = await launcher.launch({ headless: true, ...options });
			await browser.close();
		} catch (error) {
			failed.push(`${name}: ${String(error && error.message).split('\n')[0]}`);
		}
	}
	if (failed.length > 0) {
		const names = failed.map((line) => line.split(':')[0]).join(', ');
		const hint = 'chrome is the installed Google Chrome (channel "chrome"); firefox and webkit are Playwright builds: run `npx playwright install firefox webkit` in scripts/acceptance/graph-explorer/browser, and set PLAYWRIGHT_BROWSERS_PATH when they live outside Playwright\'s cache.';
		throw new Error(`${names} could not start:\n${failed.join('\n')}\n${hint}`);
	}
}

mod.actions.push({
	name: 'graph-ui:e2e',
	action: () => ({
		description: 'Run the Graph Explorer browser lanes against ENGINE_URL (opt-in; not part of test or CI)',
		run: async (_ctx, task) => {
			const plan = planE2e(process.env);
			await preflightE2e(plan, { fetch: (url, init) => fetch(url, init), loadPlaywright: () => loadAcceptancePlaywright(process.env) });
			const failures = [];
			for (const lane of plan.lanes) {
				for (const browser of plan.browsers) {
					const out = path.join(plan.outDir, browser);
					const args = [path.join(ACCEPTANCE_BROWSER_DIR, lane.script), plan.url, out, browser];
					if (lane.name === 'graph' && plan.engines) args.push(plan.engines);
					try {
						await execCommand('node', args, { task, cwd: ACCEPTANCE_BROWSER_DIR, env: { ...process.env, ENGINE_URL: plan.url, OUT_DIR: out } });
					} catch (error) {
						failures.push(`${lane.script} (${browser}): ${String(error && error.message).split('\n')[0]}`);
					}
				}
			}
			if (failures.length > 0) {
				throw new Error(`${failures.length} of ${plan.lanes.length * plan.browsers.length} lane runs failed (screenshots and JSON results in ${plan.outDir}):\n${failures.join('\n')}`);
			}
		},
	}),
});

module.exports = mod;
module.exports.e2e = { ACCEPTANCE_BROWSER_DIR, LANES, planE2e, preflightE2e };
