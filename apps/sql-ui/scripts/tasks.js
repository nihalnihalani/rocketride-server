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
 * SQL UI Build Module
 *
 * SQL database workbench — browse, query, design, and diagram SQL databases
 * reached through pipeline database tool nodes.
 */
const path = require('path');
const { existsSync } = require('node:fs');
const { readdir } = require('node:fs/promises');
const { createAppModule } = require('../../../scripts/lib/appModule');
const { execCommand } = require('../../../scripts/lib');

const APP_ROOT = path.join(__dirname, '..');
const TESTS_DIR = path.join(APP_ROOT, 'tests');

const mod = createAppModule({
	name: 'sql-ui',
	description: 'SQL Explorer Application',
	appRoot: APP_ROOT,
	dev: true,
});

// sql-ui:test — runs node:test (via tsx) over the tests/ directory's
// *.test.ts(x) files. The tested modules (paging, ddl, introspect, docs,
// erModel, discovery) are pure logic; all but docs.ts reach the platform
// through `import type` alone, which tsx erases. docs.ts imports Documents /
// NOOP_VFS as values, so stub-shell.cjs stands in for the platform modules
// (see its header). Runs under test targets, never as a build step (a normal
// build must not stream test output).
mod.actions.push({
	name: 'sql-ui:test',
	action: () => ({
		description: 'Test sql-ui',
		run: async (ctx, task) => {
			// Fail rather than pass silently. tests/ is tracked source, so an
			// absent directory or a pattern that stops matching is a broken
			// checkout, not an app without tests — and `builder test` runs this
			// action in CI, where returning cleanly would report the whole
			// suite green while nothing at all had run.
			if (!existsSync(TESTS_DIR)) {
				throw new Error(`No tests/ directory at ${TESTS_DIR} — sql-ui's suite is tracked source and must be present`);
			}
			const testFiles = (await readdir(TESTS_DIR, { recursive: true }))
				.filter((f) => f.endsWith('.test.ts') || f.endsWith('.test.tsx'))
				.map((f) => path.join('tests', f));
			if (testFiles.length === 0) {
				throw new Error('No sql-ui test files found under tests/ — expected at least one *.test.ts(x)');
			}
			// './' prefix required: a bare relative path in --require resolves as
			// a package name, not a file.
			await execCommand('node', ['--require', './scripts/stub-shell.cjs', '--import', 'tsx', '--test', '--test-reporter=spec', ...testFiles], { task, cwd: APP_ROOT });
		},
	}),
});

module.exports = mod;
