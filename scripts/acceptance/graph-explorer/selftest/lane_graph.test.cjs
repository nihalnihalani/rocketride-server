// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Self-test for browser/lane_graph.cjs's verdicts, without a browser or an engine:
 * a stand-in Playwright (written to a temporary PLAYWRIGHT_DIR) answers every
 * call, finds no element and reads empty text. A step that could not test what it
 * names must then be a FAIL, never a PASS.
 * Run: node --test scripts/acceptance/graph-explorer/selftest/lane_graph.test.cjs
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const LANE = path.join(__dirname, '..', 'browser', 'lane_graph.cjs');

const FAKE_PLAYWRIGHT = `
'use strict';
// Every call returns this object; nothing is visible, every text is empty.
const handler = {
	get(_target, prop) {
		if (prop === 'then') return undefined;
		if (prop === 'isVisible') return async () => false;
		if (prop === 'count') return async () => 0;
		if (prop === 'innerText') return async () => '';
		if (prop === Symbol.toPrimitive) return () => '';
		return fake;
	},
	apply() {
		return fake;
	},
};
const fake = new Proxy(function () {}, handler);
module.exports = { chromium: fake, firefox: fake, webkit: fake };
`;

test('lane_graph: the Ask step fails when the ask bar is missing', () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gx-selftest-'));
	try {
		const pw = path.join(tmp, 'pw', 'node_modules', 'playwright');
		fs.mkdirSync(pw, { recursive: true });
		fs.writeFileSync(path.join(pw, 'index.js'), FAKE_PLAYWRIGHT);
		const out = path.join(tmp, 'out');
		const res = spawnSync(process.execPath, [LANE, 'http://127.0.0.1:9', out, 'chrome', 'falkordb'], {
			env: { ...process.env, PLAYWRIGHT_DIR: path.join(tmp, 'pw') },
			encoding: 'utf8',
			timeout: 60000,
		});
		assert.ok(fs.existsSync(path.join(out, 'lane_graph.json')), `lane wrote no result file:\n${res.stdout}${res.stderr}`);
		const rows = JSON.parse(fs.readFileSync(path.join(out, 'lane_graph.json'), 'utf8'));
		const ask = rows.find((r) => r.name.startsWith('Ask without an LLM'));
		assert.ok(ask, 'the Ask step did not run');
		assert.strictEqual(ask.status, 'FAIL', `Ask step passed without an ask bar: ${JSON.stringify(ask)}`);
		assert.notStrictEqual(res.status, 0, 'lane exited 0 with failed steps');
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});
