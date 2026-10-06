// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// THE OPT-IN BROWSER LANES: graph-ui:e2e (CI-03, partial)
// =============================================================================
//
// The Playwright lanes in scripts/acceptance/graph-explorer/browser are the only checks that render the app in a real
// browser (focus restore, Escape and the inspector, the write confirmation, contrast, line numbers). They ran from
// a recipe in a README only. graph-ui:e2e runs them against an engine named in the environment, and fails with a
// sentence that says what is missing (the engine URL, the engine itself, Playwright, a browser) rather than failing
// somewhere inside a lane. It is opt-in: not part of graph-ui:test, `builder test` or any CI workflow.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

interface ILane {
	name: string;
	script: string;
}
interface IPlan {
	url: string;
	browsers: string[];
	lanes: ILane[];
	outDir: string;
	engines: string | null;
}
interface IPreflightDeps {
	fetch: (url: string, init: { signal: AbortSignal }) => Promise<{ ok: boolean; status: number }>;
	loadPlaywright: () => Record<string, { launch: (options: Record<string, unknown>) => Promise<{ close: () => Promise<void> }> }>;
}
interface IE2e {
	ACCEPTANCE_BROWSER_DIR: string;
	LANES: Record<string, string>;
	planE2e(env: Record<string, string | undefined>): IPlan;
	preflightE2e(plan: IPlan, deps: IPreflightDeps): Promise<void>;
}
interface IAction {
	name: string;
	action: () => { description?: string; steps?: unknown[]; run?: unknown };
}
const tasks = require('../scripts/tasks.js') as { actions: IAction[]; e2e: IE2e };
const REPO = path.resolve(__dirname, '..', '..', '..');

const ENV = { ENGINE_URL: 'http://127.0.0.1:5650/' };

/** Stand-ins for the network and Playwright: an engine that answers, and browsers that start. */
function deps(over: Partial<{ status: number; unreachable: string; noPlaywright: boolean; broken: string[] }> = {}): IPreflightDeps & { launched: string[] } {
	const launched: string[] = [];
	const launcher = (name: string) => ({
		launch: async (options: Record<string, unknown>) => {
			const label = options.channel === 'chrome' ? 'chrome' : name;
			if (over.broken?.includes(label)) throw new Error(`browserType.launch: Executable doesn't exist at /nowhere/${label}\nmore detail`);
			launched.push(label);
			return { close: async () => undefined };
		},
	});
	return {
		launched,
		fetch: async () => {
			if (over.unreachable) throw new TypeError('fetch failed', { cause: new Error(over.unreachable) });
			return { ok: (over.status ?? 200) < 400, status: over.status ?? 200 };
		},
		loadPlaywright: () => {
			if (over.noPlaywright) throw new Error("Cannot find module 'playwright'");
			return { chromium: launcher('chromium'), firefox: launcher('firefox'), webkit: launcher('webkit') };
		},
	};
}

test('graph-ui:e2e is a public builder action, and nothing that runs by default runs it', () => {
	const e2e = tasks.actions.find((a) => a.name === 'graph-ui:e2e');
	assert.ok(e2e, 'the action exists');
	assert.match(e2e.action().description ?? '', /opt-in/i, 'it is listed, and says it is opt-in');
	const unit = tasks.actions.find((a) => a.name === 'graph-ui:test')?.action();
	assert.ok(unit && !JSON.stringify(unit.steps ?? []).includes('e2e'), 'graph-ui:test does not include it');
	assert.ok(!String(unit.run).includes('e2e'), 'graph-ui:test does not call it');
	const walk = (dir: string): string[] => fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)]));
	const ci = walk(path.join(REPO, '.github'));
	assert.ok(
		ci.some((file) => file.endsWith('ci.yml')),
		'the CI workflows were read'
	);
	for (const file of ci) assert.ok(!fs.readFileSync(file, 'utf8').includes('graph-ui:e2e'), `${path.relative(REPO, file)} runs it in CI`);
});

test('every lane it runs is a committed pass/fail lane in the acceptance folder', () => {
	assert.deepEqual(Object.keys(tasks.e2e.LANES), ['graph', 'sql', 'a11y', 'linenumbers']);
	for (const script of Object.values(tasks.e2e.LANES)) assert.ok(fs.existsSync(path.join(tasks.e2e.ACCEPTANCE_BROWSER_DIR, script)), script);
	assert.equal(path.relative(REPO, tasks.e2e.ACCEPTANCE_BROWSER_DIR), path.join('scripts', 'acceptance', 'graph-explorer', 'browser'));
});

test('without an engine URL it fails at once and says which variable to set and where the recipe is', () => {
	for (const env of [{}, { ENGINE_URL: '' }, { ENGINE_URL: '   ' }]) {
		assert.throws(
			() => tasks.e2e.planE2e(env),
			(error: Error) => /ENGINE_URL/.test(error.message) && /scripts\/acceptance\/graph-explorer\/README\.md/.test(error.message)
		);
	}
	assert.throws(() => tasks.e2e.planE2e({ ENGINE_URL: '127.0.0.1:5650' }), /ENGINE_URL must be an http\(s\) URL/);
	assert.throws(() => tasks.e2e.planE2e({ ENGINE_URL: 'ftp://127.0.0.1:5650' }), /ENGINE_URL must be an http\(s\) URL/);
});

test('the plan: Chrome and every lane by default, a choice of browsers, lanes and graph engines, and results outside the tree', () => {
	const plan = tasks.e2e.planE2e(ENV);
	assert.equal(plan.url, 'http://127.0.0.1:5650', 'no trailing slash: the lanes append paths');
	assert.deepEqual(plan.browsers, ['chrome']);
	assert.deepEqual(
		plan.lanes.map((l) => l.name),
		['graph', 'sql', 'a11y', 'linenumbers']
	);
	assert.equal(plan.engines, null);
	assert.equal(path.relative(REPO, plan.outDir), path.join('scripts', 'acceptance', 'graph-explorer', 'out', 'e2e'), "the acceptance folder's git-ignored out/");
	assert.deepEqual(tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_BROWSERS: 'all' }).browsers, ['chrome', 'firefox', 'webkit']);
	assert.deepEqual(tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_BROWSERS: ' webkit , chrome ' }).browsers, ['webkit', 'chrome']);
	assert.deepEqual(
		tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_LANES: 'sql,graph' }).lanes.map((l) => l.script),
		['lane_sql.cjs', 'lane_graph.cjs']
	);
	assert.equal(tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_ENGINES: 'neo4j,age' }).engines, 'neo4j,age');
	assert.equal(tasks.e2e.planE2e({ ...ENV, OUT_DIR: '/tmp/somewhere' }).outDir, '/tmp/somewhere');
	assert.throws(() => tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_BROWSERS: 'chrome,edge' }), /Unknown browser "edge".*chrome, firefox, webkit, all/);
	assert.throws(() => tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_LANES: 'graph,perf' }), /Unknown lane "perf".*graph, sql, a11y, linenumbers/);
	assert.throws(() => tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_ENGINES: 'neo4j,arango' }), /Unknown graph engine "arango".*age, neo4j, falkordb/);
});

test('the preflight passes only when the engine answers, Playwright loads and every chosen browser starts', async () => {
	const ok = deps();
	await tasks.e2e.preflightE2e(tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_BROWSERS: 'all' }), ok);
	assert.deepEqual(ok.launched, ['chrome', 'firefox', 'webkit'], 'Chrome is the installed Google Chrome (channel chrome)');
});

test('the preflight names what is missing: the engine, Playwright, or a browser', async () => {
	const plan = tasks.e2e.planE2e(ENV);
	await assert.rejects(tasks.e2e.preflightE2e(plan, deps({ unreachable: 'connect ECONNREFUSED 127.0.0.1:5650' })), /No engine answered at http:\/\/127\.0\.0\.1:5650 \(connect ECONNREFUSED 127\.0\.0\.1:5650\)/);
	await assert.rejects(tasks.e2e.preflightE2e(plan, deps({ status: 503 })), /The engine at http:\/\/127\.0\.0\.1:5650 answered HTTP 503/);
	await assert.rejects(tasks.e2e.preflightE2e(plan, deps({ noPlaywright: true })), /Playwright is not installed.*npm install --no-package-lock.*PLAYWRIGHT_DIR/s);
	const all = tasks.e2e.planE2e({ ...ENV, GRAPH_UI_E2E_BROWSERS: 'all' });
	await assert.rejects(tasks.e2e.preflightE2e(all, deps({ broken: ['firefox', 'webkit'] })), (error: Error) => {
		assert.match(error.message, /firefox, webkit could not start/);
		assert.match(error.message, /firefox: browserType\.launch: Executable doesn't exist at \/nowhere\/firefox$/m, 'the first line of each failure');
		assert.match(error.message, /npx playwright install firefox webkit/);
		assert.match(error.message, /PLAYWRIGHT_BROWSERS_PATH/);
		return true;
	});
	await assert.rejects(tasks.e2e.preflightE2e(plan, deps({ broken: ['chrome'] })), /chrome could not start.*Google Chrome/s);
});
