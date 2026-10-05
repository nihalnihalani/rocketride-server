// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Runs a browser lane against a stand-in Playwright that models an empty page:
 * every call succeeds, nothing is visible, every text is empty, and
 * page.evaluate() returns what the lane's in-page function would read from a
 * page with nothing on it. A lane check that could not observe what it names
 * must then record FAIL, never PASS. Used by the *.test.cjs files here.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const FAKE_PLAYWRIGHT = `
'use strict';
// What a lane's page.evaluate() callback would return on an empty page.
function emptyPage(fn, arg) {
	const src = String(fn);
	if (fn.name === 'scanContrast') return { scopeFound: arg === 'body', rows: [], strokes: [] };
	if (src.includes('runningCanvasAnimations')) return { frames: 0, transformChanges: 0, runningCanvasAnimations: null };
	if (src.includes('line-numbers')) return [];
	return '';
}
// Every other call returns this object; nothing is visible, every text is empty.
const handler = {
	get(_target, prop) {
		if (prop === 'then') return undefined;
		if (prop === 'isVisible') return async () => false;
		if (prop === 'count') return async () => 0;
		if (prop === 'innerText') return async () => '';
		if (prop === 'evaluate') return async (fn, arg) => emptyPage(fn, arg);
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

/**
 * Run `browser/<lane>` with the stand-in and return its exit status, output and result rows.
 * @param {string} lane - File name under browser/, e.g. 'lane_graph.cjs'.
 * @param {string[]} args - Lane arguments after the base URL and output folder.
 * @param {string} resultFile - The JSON file the lane writes into its output folder.
 */
function runWithStandIn(lane, args, resultFile) {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gx-selftest-'));
	try {
		const pw = path.join(tmp, 'pw', 'node_modules', 'playwright');
		fs.mkdirSync(pw, { recursive: true });
		fs.writeFileSync(path.join(pw, 'index.js'), FAKE_PLAYWRIGHT);
		const out = path.join(tmp, 'out');
		const res = spawnSync(process.execPath, [path.join(__dirname, '..', 'browser', lane), 'http://127.0.0.1:9', out, ...args], {
			env: { ...process.env, PLAYWRIGHT_DIR: path.join(tmp, 'pw') },
			encoding: 'utf8',
			timeout: 60000,
		});
		const file = path.join(out, resultFile);
		if (!fs.existsSync(file)) throw new Error(`${lane} wrote no ${resultFile}:\n${res.stdout}${res.stderr}`);
		return { status: res.status, stdout: res.stdout, data: JSON.parse(fs.readFileSync(file, 'utf8')) };
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
}

module.exports = { runWithStandIn };
