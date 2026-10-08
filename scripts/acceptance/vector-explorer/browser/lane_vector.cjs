// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Browser lane (production shell served by the real engine): Vector Explorer's
 * management console. Chrome (installed, channel "chrome"), one fresh context.
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
 *     sends nothing; once on 127.0.0.1 and once on the LAN origin (LAN_URL)
 *   a chat answer carries at least one source; "open" lands on that chunk
 *   trash: Cancel is focused, Cancel sends nothing, Confirm removes exactly
 *     that document and the stats drop
 *   the 1,500-document store loads to completion with the progress line and
 *     without reshuffling the rows already shown
 *   sign-out leaves no task token in the page's storage
 *   privacy: no response carries a full-dimension float array except vectors
 *     (two keys at most) and embed answers; no request carries one other than
 *     a query vector embed returned in this session
 *
 * The store's side of each step is read through the TypeScript client
 * (packages/client-typescript/dist/cjs; ./builder client-typescript:build) with
 * the fixture's Tools task token, never through the page.
 *
 * Usage: node lane_vector.cjs [base-url] [out-dir] [fixture]
 *   (base-url and out-dir default to ENGINE_URL and OUT_DIR; fixture is a key of
 *   env.cjs FIXTURES, default qdrant). LAN_URL: the same engine on a LAN address.
 */
'use strict';
/* global document, localStorage, sessionStorage */
const E = require('../env.cjs');
const nodeCrypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const [, , base = E.ENGINE_URL, out = E.OUT_DIR, fixtureKey = 'qdrant'] = process.argv;
const RUN = nodeCrypto.randomBytes(4).toString('hex');
const DIMENSION = 384;
const WATER_QUESTION = 'Where does Falcon Station get its drinking water?';
const results = [];

// Everything the lane looks for in the app, in one place (APP_SPEC wording).
const UI = {
	launcher: 'Open Vector Explorer',
	openConsole: [/^Open console$/i, /^Open documents$/i, /^Open$/i],
	statsDocuments: /Documents\s*\n?\s*([\d,]+)/,
	directoryCount: /([\d,]+)\s+documents/,
	chunksAdded: /([\d,]+)\s+chunks?\s+added/,
	replace: /Replace existing/,
	chatBox: /Ask about these documents/i,
	askButton: /^Ask$/,
	sourceOpen: /^open$/i,
	trash: (p) => `Remove ${p} from the database`,
	removeConfirm: 'Remove document',
	loading: /Loading documents…/,
	readOnly: /Read-only/,
	logout: 'Log out',
};

fs.mkdirSync(out, { recursive: true });

function rec(name, ok, detail) {
	results.push({ fixture: fixtureKey, name, status: ok ? 'PASS' : 'FAIL', detail });
	console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${fixtureKey}: ${name}${!ok && detail ? ` -- ${String(detail).slice(0, 220)}` : ''}`);
}

async function step(page, name, fn) {
	try {
		const detail = await fn();
		rec(name, detail === true, detail === true ? undefined : `returned ${JSON.stringify(detail)}`);
	} catch (e) {
		rec(name, false, String(e && e.message ? e.message : e).split('\n')[0]);
	}
	await page.screenshot({ path: path.join(out, `vector-${fixtureKey}-${name.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)}.png`) }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Helpers that need no browser
// ---------------------------------------------------------------------------

/** The objectId the engine derives for an upload named `name`: uuid5(NAMESPACE_URL, 'null://Stream/' + name). */
function objectId(name) {
	const ns = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex');
	const hash = nodeCrypto.createHash('sha1').update(Buffer.concat([ns, Buffer.from('null://Stream/' + name, 'utf8')])).digest();
	const b = Buffer.from(hash.subarray(0, 16));
	b[6] = (b[6] & 0x0f) | 0x50;
	b[8] = (b[8] & 0x3f) | 0x80;
	const h = b.toString('hex');
	return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** A minimal one-page PDF whose text layer is `text` (ASCII). */
function makePdf(text) {
	const esc = text.replace(/[\\()]/g, (c) => '\\' + c);
	const stream = `BT /F1 12 Tf 72 720 Td (${esc}) Tj ET`;
	const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>', `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
	let body = '%PDF-1.4\n';
	const offsets = [];
	objects.forEach((obj, i) => {
		offsets.push(body.length);
		body += `${i + 1} 0 obj\n${obj}\nendobj\n`;
	});
	const xref = body.length;
	body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` + offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
	body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(body, 'latin1');
}

/** Every float array of exactly `dim` numbers inside `value`, with the key path that holds it. */
function fullVectors(value, dim = DIMENSION, at = '$', found = []) {
	if (Array.isArray(value)) {
		if (value.length === dim && value.every((x) => typeof x === 'number') && value.some((x) => !Number.isInteger(x))) found.push({ at, vector: value });
		else value.forEach((v, i) => fullVectors(v, dim, `${at}[${i}]`, found));
	} else if (value && typeof value === 'object') {
		for (const [k, v] of Object.entries(value)) fullVectors(v, dim, `${at}.${k}`, found);
	}
	return found;
}

/** The tool name a DAP request asks for, when it is a tool call. */
function toolOf(request) {
	const args = (request && request.arguments) || {};
	return args.tool || (args.arguments && args.arguments.tool) || args.tool_name || null;
}

// Columns of n values in sample/project/neighbors answers: n may equal the dimension by chance.
const COLUMN_TOOLS = new Set(['sample', 'project', 'neighbors']);
const COLUMN_PATH = /\.(points\.\w+|density|outliers|knn\.\w+|similarities|scores)$/;

/**
 * The privacy property over captured WebSocket frames (parsed JSON, in order).
 * Returns a list of violations (empty when the property holds).
 */
function privacyViolations(frames, dim = DIMENSION) {
	const requests = new Map();
	const embedded = [];
	const violations = [];
	for (const { dir, msg } of frames) {
		if (dir === 'sent' && msg && msg.type === 'request') {
			requests.set(msg.seq, msg);
			for (const hit of fullVectors(msg.arguments, dim)) {
				if (!embedded.some((v) => v.length === hit.vector.length && v.every((x, i) => x === hit.vector[i]))) violations.push(`request ${toolOf(msg) || msg.command} carries a ${dim}-float array at ${hit.at} that no embed answer returned`);
			}
		} else if (dir === 'received' && msg && msg.type === 'response') {
			const req = requests.get(msg.request_seq);
			const tool = toolOf(req);
			const hits = fullVectors(msg.body, dim).filter((h) => !(COLUMN_TOOLS.has(tool) && COLUMN_PATH.test(h.at)));
			if (!hits.length) continue;
			if (tool === 'embed') {
				hits.forEach((h) => embedded.push(h.vector));
			} else if (tool === 'vectors') {
				if (hits.length > 2) violations.push(`a vectors answer carries ${hits.length} vectors (at most 2)`);
			} else {
				violations.push(`response to ${tool || (req && req.command) || 'an unknown request'} carries a ${dim}-float array at ${hits[0].at}`);
			}
		}
	}
	return violations;
}

// ---------------------------------------------------------------------------
// The store's side, through the TypeScript client (never through the page)
// ---------------------------------------------------------------------------

let sdk = null;
async function server() {
	if (sdk) return sdk;
	let mod;
	try {
		mod = require(path.join(E.CLIENT_TS_DIR, 'dist', 'cjs', 'client', 'index.js'));
	} catch (e) {
		throw new Error(`the TypeScript client is not built (./builder client-typescript:build): ${e.message.split('\n')[0]}`);
	}
	const client = new mod.RocketRideClient({ auth: E.API_KEY, uri: base });
	await client.connect();
	sdk = client;
	return client;
}

async function tokenOf(fixture, source) {
	const client = await server();
	const tasks = await client.getTasks();
	const row = tasks.find((t) => ((t.pipeline || {}).project_id === fixture.projectId) && t.source === source);
	if (!row) throw new Error(`${fixture.name} / ${source} is not running (start_fixtures.py)`);
	return row.token;
}

async function storeTool(tool, input, fixture = E.FIXTURES[fixtureKey]) {
	const client = await server();
	return client.tool({ token: await tokenOf(fixture, 'tools_1'), tool, nodeId: 'store_1', input, timeout: 60000 });
}

async function storeHas(name) {
	const answer = await storeTool('chunks', { object_id: objectId(name), limit: 1 });
	return answer && answer.success === true;
}

// ---------------------------------------------------------------------------
// Page helpers
// ---------------------------------------------------------------------------

async function bodyText(page) {
	return page.locator('body').innerText();
}

async function openConsole(page, fixture) {
	await page.getByText(fixture.name).first().click();
	for (const name of UI.openConsole) {
		const button = page.getByRole('button', { name }).first();
		if (await button.isVisible().catch(() => false)) {
			await button.click();
			break;
		}
	}
	await page.getByText(UI.statsDocuments).first().waitFor({ timeout: 60000 });
}

async function statsDocuments(page) {
	const m = UI.statsDocuments.exec(await bodyText(page));
	return m ? Number(m[1].replace(/,/g, '')) : null;
}

async function uploadFiles(page, files) {
	await page.locator('input[type="file"]:not([webkitdirectory])').first().setInputFiles(files);
}

async function uploadFolder(page, dir) {
	await page.locator('input[type="file"][webkitdirectory]').first().setInputFiles(dir);
}

async function focusedText(page) {
	return page.evaluate(() => (document.activeElement ? document.activeElement.textContent || '' : ''));
}

// ---------------------------------------------------------------------------
// The lane
// ---------------------------------------------------------------------------

async function main() {
	const { chromium } = E.loadPlaywright();
	const fixture = E.FIXTURES[fixtureKey];
	if (!fixture) throw new Error(`unknown fixture ${fixtureKey}; known: ${Object.keys(E.FIXTURES).join(', ')}`);
	const work = fs.mkdtempSync(path.join(os.tmpdir(), 'vx-lane-'));
	const browser = await chromium.launch({ channel: 'chrome', headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
	const page = await context.newPage();
	const frames = [];
	page.on('websocket', (ws) => {
		ws.on('framesent', (f) => {
			try {
				frames.push({ dir: 'sent', msg: JSON.parse(String(f.payload)) });
			} catch {
				// binary or non-JSON frame
			}
		});
		ws.on('framereceived', (f) => {
			try {
				frames.push({ dir: 'received', msg: JSON.parse(String(f.payload)) });
			} catch {
				// binary or non-JSON frame
			}
		});
	});
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
			const text = await bodyText(page);
			if (!text.includes(E.FIXTURES.stock_rag.name)) return 'the stock RAG pipeline has no card';
			return UI.readOnly.test(text) ? true : 'no Read-only card';
		});

		let before = null;
		await step(page, "the console's stats match the store's own answer", async () => {
			await openConsole(page, fixture);
			const shown = await statsDocuments(page);
			const stats = await storeTool('stats', { mode: 'full' });
			before = shown;
			return shown !== null && stats.success === true && shown === stats.documents ? true : `shown ${shown}, store ${JSON.stringify(stats.documents)}`;
		});

		await step(page, 'an upload adds a document and grows the stats', async () => {
			const file = path.join(work, own.single);
			fs.writeFileSync(file, `# Lane note ${RUN}\n\nThe lane uploads this note to check the ingest panel. Glassbrook spring feeds the settling tank.\n`);
			await uploadFiles(page, [file]);
			await page.getByText(UI.chunksAdded).first().waitFor({ timeout: 120000 });
			if (!(await storeHas(own.single))) return 'the store does not have the uploaded document';
			await page.waitForFunction((n) => /Documents\s*\n?\s*([\d,]+)/.test(document.body.innerText) && Number(/Documents\s*\n?\s*([\d,]+)/.exec(document.body.innerText)[1].replace(/,/g, '')) === n, before + 1, { timeout: 30000 });
			return true;
		});

		await step(page, 'a folder upload stores nested paths', async () => {
			const file = path.join(work, own.nested);
			fs.mkdirSync(path.dirname(file), { recursive: true });
			fs.writeFileSync(file, `# Nested note ${RUN}\n\nA note two folders deep.\n`);
			await uploadFolder(page, path.join(work, own.folder));
			await page.getByText(UI.chunksAdded).nth(1).waitFor({ timeout: 120000 });
			if (!(await storeHas(own.nested))) return `the store has no document named ${own.nested}`;
			return (await bodyText(page)).includes('deeper') ? true : 'the directory does not show the nested folder';
		});

		await step(page, 'two report.pdf files land on two rows, each attributed to its own document', async () => {
			const dir = path.join(work, `${own.folder}-reports`, own.folder);
			for (const [sub, word] of [['a', 'alpha'], ['b', 'bravo']]) {
				fs.mkdirSync(path.join(dir, sub), { recursive: true });
				fs.writeFileSync(path.join(dir, sub, 'report.pdf'), makePdf(`Report ${word} ${RUN} for the lane.`));
			}
			fs.rmSync(path.join(work, own.folder), { recursive: true, force: true });
			await uploadFolder(page, dir);
			await page.waitForTimeout(1000);
			const rows = await page.getByText(/report\.pdf/).count();
			if (rows < 2) return `${rows} rows name report.pdf`;
			for (const [name, word] of [[own.reportA, 'alpha'], [own.reportB, 'bravo']]) {
				const answer = await storeTool('chunks', { object_id: objectId(name), limit: 5 });
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
					await page.getByRole('button', { name: UI.launcher }).click();
					await openConsole(page, fixture);
				}
				const file = path.join(work, own.single);
				fs.writeFileSync(file, `# Changed ${RUN}\n\nThis text must never reach the store.\n`);
				await uploadFiles(page, [file]);
				await page.getByText(UI.replace).first().waitFor({ timeout: 30000 });
				const focused = (await focusedText(page)).trim();
				if (focused !== 'Cancel') return `focus is on ${JSON.stringify(focused)}, not Cancel`;
				await page.getByRole('button', { name: 'Cancel' }).first().click();
				await page.waitForTimeout(1500);
				const answer = await storeTool('chunks', { object_id: objectId(own.single), limit: 5 });
				if (!answer.success) return 'the stored document is gone after Cancel';
				return answer.items.some((c) => String(c.content).includes('must never reach')) ? 'the replacement reached the store after Cancel' : true;
			});
		};
		await replaceStep('127.0.0.1', base);
		// The LAN origin needs the engine listening on that address (LAN_URL, e.g. http://<this host's address>:5590).
		await replaceStep('LAN origin', process.env.LAN_URL || null);

		await step(page, 'a chat answer carries sources and "open" lands on the chunk', async () => {
			await page.getByRole('textbox', { name: UI.chatBox }).first().fill(WATER_QUESTION);
			await page.getByRole('button', { name: UI.askButton }).first().click();
			await page.getByText(E.STUB_LLM_TAG).first().waitFor({ timeout: 120000 });
			const opens = page.getByRole('button', { name: UI.sourceOpen });
			if ((await opens.count()) < 1) return 'the answer shows no source';
			await opens.first().click();
			await page.waitForTimeout(1000);
			return /#\s?\d+|chunk/i.test(await bodyText(page)) ? true : 'no chunk shown after open';
		});

		await step(page, 'trash: Cancel focused and sending nothing, Confirm removes exactly that document', async () => {
			const shown = await statsDocuments(page);
			const trash = page.getByRole('button', { name: UI.trash(own.single) }).first();
			await trash.click();
			await page.getByRole('button', { name: UI.removeConfirm }).first().waitFor({ timeout: 15000 });
			const focused = (await focusedText(page)).trim();
			if (focused !== 'Cancel') return `focus is on ${JSON.stringify(focused)}, not Cancel`;
			await page.getByRole('button', { name: 'Cancel' }).first().click();
			if (!(await storeHas(own.single))) return 'Cancel removed the document';
			await trash.click();
			await page.getByRole('button', { name: UI.removeConfirm }).first().click();
			await page.waitForTimeout(2000);
			if (await storeHas(own.single)) return 'Confirm did not remove the document';
			if (!(await storeHas(own.nested))) return 'Confirm removed another document';
			const after = await statsDocuments(page);
			return shown !== null && after === shown - 1 ? true : `stats ${shown} -> ${after}`;
		});

		await step(page, 'the 1,500-document store loads to completion without reshuffling', async () => {
			await page.getByRole('button', { name: UI.launcher }).click().catch(() => {});
			await page.getByText(E.FIXTURES.qdrant_pager.name).first().click();
			for (const name of UI.openConsole) {
				const b = page.getByRole('button', { name }).first();
				if (await b.isVisible().catch(() => false)) {
					await b.click();
					break;
				}
			}
			await page.getByText(UI.loading).first().waitFor({ timeout: 60000 });
			const firstRow = async () => (await bodyText(page)).split('\n').find((l) => /note-\d{4}\.txt/.test(l)) || null;
			const early = await firstRow();
			await page.waitForTimeout(500);
			const later = (await page.getByText(UI.loading).count()) > 0 ? await firstRow() : early;
			if (early === null || early !== later) return `rows reshuffled while loading: ${early} -> ${later}`;
			await page.getByText(UI.loading).first().waitFor({ state: 'detached', timeout: 120000 });
			const m = UI.directoryCount.exec(await bodyText(page));
			const n = m ? Number(m[1].replace(/,/g, '')) : null;
			return n === E.PAGER_DOCUMENTS ? true : `the directory shows ${n} documents`;
		});

		await step(page, 'sign-out leaves no task token in the page storage', async () => {
			const client = await server();
			const tokens = (await client.getTasks()).map((t) => t.token).filter(Boolean);
			const menu = page.locator('[aria-haspopup="menu"]').last();
			await menu.click();
			await page.getByText(UI.logout).first().click();
			await page.waitForTimeout(1500);
			const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
			if (!tokens.length) return 'no running tasks to check against';
			const leaked = tokens.filter((t) => stored.includes(t));
			return leaked.length === 0 && /sign in/i.test(await bodyText(page)) ? true : `${leaked.length} task tokens left in storage`;
		});

		await step(page, 'privacy: no full-dimension vectors outside vectors and embed answers', async () => {
			if (!frames.length) return 'no WebSocket frames were captured';
			const violations = privacyViolations(frames);
			return violations.length === 0 ? true : violations.slice(0, 3).join('; ');
		});
	} finally {
		// Clean up the lane's own documents through the store (never the demo ones).
		try {
			const ids = Object.values(own).filter((n) => /\.(md|pdf)$/.test(n)).map(objectId);
			await storeTool('remove_document', { object_ids: ids });
		} catch {
			// best effort
		}
		await browser.close().catch(() => {});
		if (sdk) await sdk.disconnect().catch(() => {});
		fs.rmSync(work, { recursive: true, force: true });
		fs.writeFileSync(path.join(out, 'lane_vector.json'), JSON.stringify(results, null, 2));
	}
	const failed = results.filter((r) => r.status !== 'PASS').length;
	console.log(`${results.length - failed} of ${results.length} steps passed`);
	process.exitCode = failed ? 1 : 0;
}

if (require.main === module) {
	main().catch((e) => {
		console.error(e);
		fs.writeFileSync(path.join(out, 'lane_vector.json'), JSON.stringify(results, null, 2));
		process.exitCode = 1;
	});
}

module.exports = { objectId, makePdf, fullVectors, privacyViolations };
