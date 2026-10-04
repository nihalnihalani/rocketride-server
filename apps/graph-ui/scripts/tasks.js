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

// Suites that must exist for the gate to mean anything. A missing file here is
// a broken checkout or a deleted suite, not an app "without tests", so the
// gate fails instead of running whatever happens to be left.
const REQUIRED_TESTS = ['scaffold.test.ts', 'lexer.test.ts', 'split.test.ts', 'classify.test.ts', 'quote.test.ts'];

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

module.exports = mod;
