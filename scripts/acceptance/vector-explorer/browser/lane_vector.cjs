// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Browser lane (production shell served by the real engine): Vector Explorer's
 * management console (gate G3). Chrome (installed, channel "chrome"), one
 * fresh context. The map has its own lane (lane_vector_map.cjs, gate G4).
 *
 * Fixtures: start_fixtures.py (the four template fixtures, stock_rag and
 * qdrant_pager) seeded by demo/seed_demo.sh (--pager for qdrant_pager). The lane
 * works on one template fixture (argument, default qdrant) and adds and removes
 * documents of its own there, named lane-<run>...; it never touches the demo
 * documents.
 *
 * Steps (each records PASS/FAIL and a screenshot; only an explicit `true` passes):
 *   connections: one card per tools-controlled store, store_2 never, the stock
 *     RAG pipeline as a Read-only card
 *   the console's stats match the store's own answer
 *   an upload adds a document and grows the stats; the store has it
 *   a folder upload stores nested paths
 *   two files named report.pdf in different folders land on two rows, each
 *     attributed to its own document
 *   re-uploading a stored path asks before replacing (Cancel focused); Cancel
 *     sends nothing (no upload request in the page's frames, the store
 *     unchanged); once on 127.0.0.1 and once on the LAN origin (LAN_URL)
 *   a chat answer carries at least one source; "open" lands on that chunk
 *   trash: Cancel is focused and sends nothing (no removal request in the
 *     page's frames, the store unchanged); Confirm removes exactly that
 *     document and the stats drop
 *   the 1,500-document store loads to completion with the progress line,
 *     the first row unchanged at every look while it loads
 *   sign-out leaves no task token in the page's storage
 *   privacy (B4): no response or event carries a float array of
 *     dialect.dimension numbers except vectors (two at most) and embed
 *     answers; no request carries one other than a query vector embed
 *     returned in this session
 *
 * The store's side of each step is read through the TypeScript client
 * (packages/client-typescript/dist/cjs; ./builder client-typescript:build) with
 * the fixture's Tools task token, never through the page. Selectors and
 * wording: ui.cjs.
 *
 * Usage: node lane_vector.cjs [base-url] [out-dir] [fixture]
 *   (base-url and out-dir default to ENGINE_URL and OUT_DIR; fixture is a key of
 *   env.cjs FIXTURES, default qdrant). LAN_URL: the same engine on a LAN address.
 * vector-ui:e2e-live runs it as `node lane_vector.cjs <base-url> <out-dir> <browser> [backends]`
 * (backends: a comma list, else VECTOR_UI_E2E_BACKENDS, else the four supported ones). The
 * lane then runs once per backend into <out-dir>/<backend> and writes every row, with its
 * browser and backend, to <out-dir>/lane_vector.json. It drives Google Chrome only.
 */
'use strict';
/* global document, localStorage, sessionStorage */
const E = require('../env.cjs');
const C = require('./common.cjs');
const { CONSOLE: UI } = require('./ui.cjs');
const nodeCrypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

/** The browsers vector-ui:e2e-live names (third argument); this lane drives Google Chrome only. */
const RUNNER_BROWSERS = ['chrome', 'firefox', 'webkit'];
/** The backends a vector-ui:e2e-live run covers when none are named. */
const RUNNER_BACKENDS = ['postgres', 'rocketride_vector', 'qdrant', 'chroma'];

/**
 * The lane's arguments: `<base-url> <out-dir> [fixture]` run directly, or
 * `<base-url> <out-dir> <browser> [backends]` from vector-ui:e2e-live.
 *
 * @param {string[]} args - process.argv without the node binary and the script.
 * @param {Record<string, string | undefined>} env - The environment.
 * @returns {{ base: string, out: string, browser: string | null, fixtures: string[] }} browser is null when run directly.
 */
function laneArgs(args, env) {
	const [base = E.ENGINE_URL, out = E.OUT_DIR, third, fourth] = args;
	if (!RUNNER_BROWSERS.includes(third)) return { base, out, browser: null, fixtures: [third || 'qdrant'] };
	const named = (fourth || env.VECTOR_UI_E2E_BACKENDS || RUNNER_BACKENDS.join(','))
		.split(',')
		.map((item) => item.trim())
		.filter(Boolean);
	return { base, out, browser: third, fixtures: named };
}

const ARGS = laneArgs(process.argv.slice(2), process.env);
const { base, out } = ARGS;
const fixtureKey = ARGS.fixtures[0];
const RUN = nodeCrypto.randomBytes(4).toString('hex');

/** The writes among sent frames: removals ('remove_document', 'delete') and uploads ('upload'). */
function sentWrites(frames) {
	const out = [];
	for (const f of frames) {
		if (f.dir !== 'sent' || !f.msg || f.msg.type !== 'request') continue;
		const tool = C.toolOf(f.msg);
		if (tool === 'remove_document' || tool === 'delete') out.push(tool);
		else if (C.isUpload(f.msg)) out.push('upload');
	}
	return out;
}

/**
 * Why the first rows seen while documents loaded show a reshuffle (null when
 * they do not). Looks before the first row rendered (null) are ignored; after
 * it, any other first row (or none) is a reshuffle.
 */
function reshuffled(firstRows) {
	const start = firstRows.findIndex((r) => r !== null);
	if (start === -1) return 'no row was shown while loading';
	const seen = firstRows.slice(start);
	if (seen.length < 2) return `fewer than 2 looks at a shown row while loading (${seen.length})`;
	const changed = seen.findIndex((r) => r !== seen[0]);
	return changed === -1 ? null : `rows reshuffled while loading: ${seen[0]} -> ${seen[changed]}`;
}

async function main() {
	const { chromium } = E.loadPlaywright();
	const fixture = E.FIXTURES[fixtureKey];
	if (!fixture) throw new Error(`unknown fixture ${fixtureKey}; known: ${Object.keys(E.FIXTURES).join(', ')}`);
	const { step, write } = C.createRecorder(fixtureKey, out, 'vector');
	const store = C.storeClient(base);
	const storeHas = async (name) => {
		const answer = await store.tool(fixture, 'chunks', { object_id: C.objectId(name), limit: 1 });
		return answer && answer.success === true;
	};
	const work = fs.mkdtempSync(path.join(os.tmpdir(), 'vx-lane-'));
	const browser = await chromium.launch({ channel: 'chrome', headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
	const page = await context.newPage();
	page.setDefaultTimeout(30000);
	const capture = C.captureFrames(page);
	const statsDocuments = async () => {
		const m = UI.statsDocuments.exec(await C.bodyText(page));
		return m ? Number(m[1].replace(/,/g, '')) : null;
	};
	const uploadFiles = (files) => page.locator('input[type="file"]:not([webkitdirectory])').first().setInputFiles(files);
	const uploadFolder = (dir) => page.locator('input[type="file"][webkitdirectory]').first().setInputFiles(dir);
	const own = { single: `lane-${RUN}.md`, folder: `lane-${RUN}`, nested: `lane-${RUN}/nested/deeper/note.md`, reportA: `lane-${RUN}/a/report.pdf`, reportB: `lane-${RUN}/b/report.pdf` };
	try {
		await E.signIn(page, base);

		await step(page, 'connections: one card per tools-controlled store, store_2 never, stock RAG read-only', async () => {
			await page.getByRole('button', { name: UI.launcher }).click();
			await page.getByText(fixture.name).first().waitFor({ timeout: 60000 });
			for (const key of ['postgres', 'rocketride_vector', 'qdrant', 'chroma']) {
				const n = await page.getByText(E.FIXTURES[key].name).count();
				if (n !== 1) return `${E.FIXTURES[key].name}: ${n} cards (expected exactly 1: store_1 only)`;
			}
			const text = await C.bodyText(page);
			if (!text.includes(E.FIXTURES.stock_rag.name)) return 'the stock RAG pipeline has no card';
			return UI.readOnly.test(text) ? true : 'no Read-only card';
		});

		let before = null;
		await step(page, "the console's stats match the store's own answer", async () => {
			await C.openConnection(page, fixture);
			const shown = await statsDocuments();
			const stats = await store.tool(fixture, 'stats', { mode: 'full' });
			before = shown;
			return shown !== null && stats.success === true && shown === stats.documents ? true : `shown ${shown}, store ${JSON.stringify(stats.documents)}`;
		});

		await step(page, 'an upload adds a document and grows the stats', async () => {
			if (before === null) return 'no stats were shown (previous step)';
			const file = path.join(work, own.single);
			fs.writeFileSync(file, `# Lane note ${RUN}\n\nThe lane uploads this note to check the ingest panel. Glassbrook spring feeds the settling tank.\n`);
			await uploadFiles([file]);
			await page.getByText(UI.chunksAdded).first().waitFor({ timeout: 120000 });
			if (!(await storeHas(own.single))) return 'the store does not have the uploaded document';
			await page.waitForFunction((n) => /Documents\s*\n?\s*([\d,]+)/.test(document.body.innerText) && Number(/Documents\s*\n?\s*([\d,]+)/.exec(document.body.innerText)[1].replace(/,/g, '')) === n, before + 1, { timeout: 30000 });
			return (await statsDocuments()) === before + 1 ? true : `stats show ${await statsDocuments()}, expected ${before + 1}`;
		});

		await step(page, 'a folder upload stores nested paths', async () => {
			const file = path.join(work, own.nested);
			fs.mkdirSync(path.dirname(file), { recursive: true });
			fs.writeFileSync(file, `# Nested note ${RUN}\n\nA note two folders deep.\n`);
			await uploadFolder(path.join(work, own.folder));
			await page.getByText(UI.chunksAdded).nth(1).waitFor({ timeout: 120000 });
			if (!(await storeHas(own.nested))) return `the store has no document named ${own.nested}`;
			return (await C.bodyText(page)).includes('deeper') ? true : 'the directory does not show the nested folder';
		});

		await step(page, 'two report.pdf files land on two rows, each attributed to its own document', async () => {
			const dir = path.join(work, `${own.folder}-reports`, own.folder);
			for (const [sub, word] of [
				['a', 'alpha'],
				['b', 'bravo'],
			]) {
				fs.mkdirSync(path.join(dir, sub), { recursive: true });
				fs.writeFileSync(path.join(dir, sub, 'report.pdf'), C.makePdf(`Report ${word} ${RUN} for the lane.`));
			}
			fs.rmSync(path.join(work, own.folder), { recursive: true, force: true });
			await uploadFolder(dir);
			await page.waitForTimeout(1000);
			const rows = await page.getByText(/report\.pdf/).count();
			if (rows < 2) return `${rows} rows name report.pdf`;
			for (const [name, word] of [
				[own.reportA, 'alpha'],
				[own.reportB, 'bravo'],
			]) {
				const answer = await store.tool(fixture, 'chunks', { object_id: C.objectId(name), limit: 5 });
				if (!answer.success) return `the store has no ${name}`;
				if (!answer.items.some((c) => String(c.content).includes(word))) return `${name} does not hold its own text (${word})`;
			}
			return true;
		});

		const replaceStep = async (label, origin) => {
			await step(page, `re-uploading a stored path asks first, Cancel focused and sending nothing (${label})`, async () => {
				if (!origin) return 'LAN_URL is not set (the same engine on a LAN address)';
				if (origin !== base) {
					await E.signIn(page, origin);
					await C.openConnection(page, fixture);
				}
				const file = path.join(work, own.single);
				fs.writeFileSync(file, `# Changed ${RUN}\n\nThis text must never reach the store.\n`);
				const since = capture.frames.length;
				await uploadFiles([file]);
				await page.getByText(UI.replace).first().waitFor({ timeout: 30000 });
				const focused = (await C.focusedText(page)).trim();
				if (focused !== UI.cancel) return `focus is on ${JSON.stringify(focused)}, not Cancel`;
				await page.getByRole('button', { name: UI.cancel }).first().click();
				await page.waitForTimeout(1500);
				if (capture.sockets === 0) return 'the page opened no WebSocket';
				const sent = sentWrites(capture.frames.slice(since));
				if (sent.length) return `the page sent ${sent.join(', ')} although Cancel was chosen`;
				const answer = await store.tool(fixture, 'chunks', { object_id: C.objectId(own.single), limit: 5 });
				if (!answer.success) return 'the stored document is gone after Cancel';
				return answer.items.some((c) => String(c.content).includes('must never reach')) ? 'the replacement reached the store after Cancel' : true;
			});
		};
		await replaceStep('127.0.0.1', base);
		// The LAN origin needs the engine listening on that address (LAN_URL, e.g. http://<this host's address>:5590).
		await replaceStep('LAN origin', process.env.LAN_URL || null);

		await step(page, 'a chat answer carries sources and "open" lands on the chunk', async () => {
			await page.getByRole('textbox', { name: UI.chatBox }).first().fill(E.WATER_QUESTION);
			await page.getByRole('button', { name: UI.askButton }).first().click();
			await page.getByText(E.STUB_LLM_TAG).first().waitFor({ timeout: 120000 });
			if (!(await C.bodyText(page)).includes(E.STUB_LLM_TAG)) return 'no stub answer is shown';
			const opens = page.getByRole('button', { name: UI.sourceOpen });
			if ((await opens.count()) < 1) return 'the answer shows no source';
			await opens.first().click();
			await page.waitForTimeout(1000);
			return /#\s?\d+|chunk/i.test(await C.bodyText(page)) ? true : 'no chunk shown after open';
		});

		await step(page, 'trash: Cancel focused and sending nothing, Confirm removes exactly that document', async () => {
			const shown = await statsDocuments();
			const trash = page.getByRole('button', { name: UI.trash(own.single) }).first();
			const since = capture.frames.length;
			await trash.click();
			await page.getByRole('button', { name: UI.removeConfirm }).first().waitFor({ timeout: 15000 });
			const focused = (await C.focusedText(page)).trim();
			if (focused !== UI.cancel) return `focus is on ${JSON.stringify(focused)}, not Cancel`;
			await page.getByRole('button', { name: UI.cancel }).first().click();
			await page.waitForTimeout(1000);
			if (capture.sockets === 0) return 'the page opened no WebSocket';
			const sent = sentWrites(capture.frames.slice(since));
			if (sent.length) return `the page sent ${sent.join(', ')} although Cancel was chosen`;
			if (!(await storeHas(own.single))) return 'Cancel removed the document';
			await trash.click();
			await page.getByRole('button', { name: UI.removeConfirm }).first().click();
			await page.waitForTimeout(2000);
			if (await storeHas(own.single)) return 'Confirm did not remove the document';
			if (!(await storeHas(own.nested))) return 'Confirm removed another document';
			const after = await statsDocuments();
			return shown !== null && after === shown - 1 ? true : `stats ${shown} -> ${after}`;
		});

		await step(page, 'the 1,500-document store loads to completion without reshuffling', async () => {
			await C.openConnection(page, E.FIXTURES.qdrant_pager).catch(() => {});
			await page.getByText(UI.loading).first().waitFor({ timeout: 60000 });
			const firstRow = async () => (await C.bodyText(page)).split('\n').find((l) => /note-\d{4}\.txt/.test(l)) || null;
			// Look at the first row again and again while "Loading documents…" is shown.
			const looks = [];
			const deadline = Date.now() + 120000;
			while (Date.now() < deadline && (await page.getByText(UI.loading).count()) > 0 && looks.length < 400) {
				looks.push(await firstRow());
				// The first page is in before the progress line shows; 5 s without a row is a failure.
				if (looks.length >= 20 && looks.every((r) => r === null)) break;
				await C.sleep(250);
			}
			const problem = reshuffled(looks);
			if (problem) return problem;
			await page.getByText(UI.loading).first().waitFor({ state: 'detached', timeout: 120000 });
			const m = UI.directoryCount.exec(await C.bodyText(page));
			const n = m ? Number(m[1].replace(/,/g, '')) : null;
			return n === E.PAGER_DOCUMENTS ? true : `the directory shows ${n} documents`;
		});

		await step(page, 'sign-out leaves no task token in the page storage', async () => {
			const tokens = (await store.runningTasks()).map((t) => t.token).filter(Boolean);
			const menu = page.locator('[aria-haspopup="menu"]').last();
			await menu.click();
			await page.getByText(UI.logout).first().click();
			await page.waitForTimeout(1500);
			const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
			if (!tokens.length) return 'no running tasks to check against';
			if (typeof stored !== 'string' || !stored.startsWith('{')) return 'the page storage could not be read';
			const leaked = tokens.filter((t) => stored.includes(t));
			return leaked.length === 0 && UI.signIn.test(await C.bodyText(page)) ? true : `${leaked.length} task tokens left in storage`;
		});

		await step(page, 'privacy: no full-dimension vectors outside vectors and embed answers', async (note) => {
			if (!capture.frames.length) return 'no WebSocket frames were captured';
			const dimension = await store.dimension(fixture);
			note({ dimension, frames: capture.frames.length });
			const violations = C.privacyViolations(capture.frames, dimension);
			return violations.length === 0 ? true : violations.slice(0, 3).join('; ');
		});
	} finally {
		// Clean up the lane's own documents through the store (never the demo ones).
		try {
			const ids = Object.values(own)
				.filter((n) => /\.(md|pdf)$/.test(n))
				.map(C.objectId);
			await store.tool(fixture, 'remove_document', { object_ids: ids });
		} catch {
			// best effort
		}
		await browser.close().catch(() => {});
		await store.close();
		fs.rmSync(work, { recursive: true, force: true });
		write('lane_vector.json');
	}
}

/**
 * A vector-ui:e2e-live run: the lane once per backend, each in its own process and folder, then
 * every row (with its browser and backend) in <out>/lane_vector.json.
 *
 * @param {ReturnType<typeof laneArgs>} args - The arguments (browser set).
 * @returns {number} The exit code: 0 only when every row passed.
 */
function runForE2e(args) {
	const { spawnSync } = require('child_process');
	const rows = [];
	for (const key of args.fixtures) {
		if (args.browser !== 'chrome') {
			rows.push({ browser: args.browser, backend: key, fixture: key, name: 'lane', status: 'FAIL', detail: `the console lane drives Google Chrome only, not ${args.browser}` });
			continue;
		}
		const sub = path.join(args.out, key);
		const file = path.join(sub, 'lane_vector.json');
		fs.rmSync(file, { force: true });
		const run = spawnSync(process.execPath, [__filename, args.base, sub, key], { stdio: 'inherit', env: process.env });
		let data = null;
		try {
			data = JSON.parse(fs.readFileSync(file, 'utf8'));
		} catch {
			data = null;
		}
		if (!Array.isArray(data)) data = [{ fixture: key, name: 'lane', status: 'FAIL', detail: `the lane wrote no result (exit ${run.status})` }];
		for (const row of data) rows.push({ browser: args.browser, backend: key, ...row });
	}
	fs.mkdirSync(args.out, { recursive: true });
	fs.writeFileSync(path.join(args.out, 'lane_vector.json'), JSON.stringify(rows, null, 2));
	const failed = rows.filter((r) => r.status !== 'PASS').length;
	console.log(`${rows.length - failed} of ${rows.length} steps passed over ${args.fixtures.join(', ')}`);
	return failed || rows.length === 0 ? 1 : 0;
}

if (require.main === module && ARGS.browser !== null) {
	process.exitCode = runForE2e(ARGS);
} else if (require.main === module) {
	main()
		.then(() => {
			const data = JSON.parse(fs.readFileSync(path.join(out, 'lane_vector.json'), 'utf8'));
			const failed = data.filter((r) => r.status !== 'PASS').length;
			console.log(`${data.length - failed} of ${data.length} steps passed`);
			process.exitCode = failed ? 1 : 0;
		})
		.catch((e) => {
			console.error(e);
			const file = path.join(out, 'lane_vector.json');
			if (!fs.existsSync(file)) {
				fs.mkdirSync(out, { recursive: true });
				fs.writeFileSync(file, JSON.stringify([{ fixture: fixtureKey, name: 'lane', status: 'FAIL', detail: String(e && e.message ? e.message : e) }], null, 2));
			}
			process.exitCode = 1;
		});
}

module.exports = { reshuffled, sentWrites, laneArgs };
