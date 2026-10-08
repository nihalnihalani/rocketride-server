// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Helpers the Vector Explorer browser lanes share: the step recorder (only an
 * explicit `true` passes), the WebSocket frame capture and the tool calls the
 * page made, the store's own side read through the TypeScript client with the
 * fixture's task token (never through the page), the B4 privacy property, and
 * page helpers that read numbers defensively (a missing value is null, never 0).
 */
'use strict';
/* global document */
const nodeCrypto = require('crypto');
const fs = require('fs');
const path = require('path');
const E = require('../env.cjs');
const { CONSOLE } = require('./ui.cjs');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------

/**
 * A recorder for one lane run. `step(page, name, fn)` runs fn(note); the step
 * passes only when fn returns exactly `true`. note(value) attaches data to the
 * step's row in the lane JSON (e.g. measured numbers), whatever the verdict.
 */
function createRecorder(fixtureKey, out, prefix) {
	const results = [];
	fs.mkdirSync(out, { recursive: true });
	function rec(name, ok, detail, extra) {
		const row = { fixture: fixtureKey, name, status: ok ? 'PASS' : 'FAIL', detail };
		if (extra !== undefined) row.extra = extra;
		results.push(row);
		console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${fixtureKey}: ${name}${!ok && detail ? ` -- ${String(detail).slice(0, 220)}` : ''}`);
	}
	async function step(page, name, fn) {
		let extra;
		const note = (value) => {
			extra = value;
		};
		try {
			const detail = await fn(note);
			rec(name, detail === true, detail === true ? undefined : `returned ${JSON.stringify(detail)}`, extra);
		} catch (e) {
			rec(name, false, String(e && e.message ? e.message : e).split('\n')[0], extra);
		}
		await page.screenshot({ path: path.join(out, `${prefix}-${fixtureKey}-${name.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)}.png`) }).catch(() => {});
	}
	function write(file) {
		fs.writeFileSync(path.join(out, file), JSON.stringify(results, null, 2));
	}
	return { results, rec, step, write };
}

// ---------------------------------------------------------------------------
// Helpers that need no browser
// ---------------------------------------------------------------------------

/** The objectId the engine derives for an upload named `name`: uuid5(NAMESPACE_URL, 'null://Stream/' + name). */
function objectId(name) {
	const ns = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex');
	const hash = nodeCrypto
		.createHash('sha1')
		.update(Buffer.concat([ns, Buffer.from('null://Stream/' + name, 'utf8')]))
		.digest();
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
function fullVectors(value, dim, at = '$', found = []) {
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

/** The node a tool call addresses ('' for a broadcast). */
function nodeOf(request) {
	const args = (request && request.arguments) || {};
	return typeof args.nodeId === 'string' ? args.nodeId : null;
}

/** True for a request that sends document bytes (the SDK's sendFiles: rrext_process open/write). */
function isUpload(request) {
	const args = (request && request.arguments) || {};
	return !!request && request.command === 'rrext_process' && (args.subcommand === 'open' || args.subcommand === 'write');
}

/** Exact equality of two numeric arrays. */
function sameVector(a, b) {
	return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i]);
}

// Columns of n values in sample/project/neighbors answers: n may equal the dimension by chance.
const COLUMN_TOOLS = new Set(['sample', 'project', 'neighbors']);
const COLUMN_PATH = /\.(points\.\w+|density|outliers|knn\.\w+|similarities|scores)$/;

/**
 * The privacy property (B4) over captured WebSocket frames (parsed JSON, in
 * order), for vectors of `dim` (dialect.dimension) floats: no response carries
 * one except `vectors` (at most 2) and `embed` answers; no event carries one;
 * no request carries one other than a vector an embed answer returned earlier.
 * Returns the violations (empty when the property holds).
 */
function privacyViolations(frames, dim) {
	if (!Number.isInteger(dim) || dim <= 0) return [`dialect.dimension is unknown (${JSON.stringify(dim)}), so the property cannot be checked`];
	const requests = new Map();
	const embedded = [];
	const violations = [];
	for (const { dir, msg } of frames) {
		if (!msg) continue;
		if (dir === 'sent' && msg.type === 'request') {
			requests.set(msg.seq, msg);
			for (const hit of fullVectors(msg.arguments, dim)) {
				if (!embedded.some((v) => sameVector(v, hit.vector))) violations.push(`request ${toolOf(msg) || msg.command} carries a ${dim}-float array at ${hit.at} that no embed answer returned`);
			}
		} else if (dir === 'received' && msg.type === 'response') {
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
		} else if (dir === 'received' && msg.type === 'event') {
			const hits = fullVectors(msg.body, dim);
			if (hits.length) violations.push(`event ${msg.event || '?'} carries a ${dim}-float array at ${hits[0].at}`);
		}
	}
	return violations;
}

// ---------------------------------------------------------------------------
// What the page sent and received
// ---------------------------------------------------------------------------

/** Capture every JSON WebSocket frame of the page, in order. */
function captureFrames(page) {
	const capture = { frames: [], sockets: 0 };
	const push = (dir, f) => {
		try {
			capture.frames.push({ dir, msg: JSON.parse(String(f.payload)) });
		} catch {
			// binary or non-JSON frame
		}
	};
	page.on('websocket', (ws) => {
		capture.sockets += 1;
		ws.on('framesent', (f) => push('sent', f));
		ws.on('framereceived', (f) => push('received', f));
	});
	return capture;
}

/**
 * The tool calls of the page for `tool` from frame index `since` on, each with
 * its answer when one arrived: { index, input, nodeId, request, result, response }.
 */
function exchanges(capture, tool, since = 0) {
	const out = [];
	const frames = capture.frames;
	for (let i = since; i < frames.length; i += 1) {
		const { dir, msg } = frames[i];
		if (dir !== 'sent' || !msg || msg.type !== 'request' || toolOf(msg) !== tool) continue;
		const args = msg.arguments || {};
		const row = { index: i, input: args.input || {}, nodeId: nodeOf(msg), request: msg, result: undefined, response: undefined };
		for (let j = i + 1; j < frames.length; j += 1) {
			const r = frames[j];
			if (r.dir === 'received' && r.msg && r.msg.type === 'response' && r.msg.request_seq === msg.seq) {
				row.response = r.msg;
				row.result = r.msg.body ? r.msg.body.result : undefined;
				break;
			}
		}
		out.push(row);
	}
	return out;
}

/** Wait for an answered `tool` call of the page after frame `since` (optionally matching `where`). */
async function waitForExchange(capture, tool, { since = 0, timeout = 60000, where = () => true } = {}) {
	const deadline = Date.now() + timeout;
	for (;;) {
		if (capture.sockets === 0) throw new Error('the page opened no WebSocket');
		const hit = exchanges(capture, tool, since).find((x) => x.response && where(x));
		if (hit) return hit;
		if (Date.now() > deadline) throw new Error(`no answered ${tool} call within ${timeout} ms`);
		await sleep(250);
	}
}

/** Requests the page sent from frame `since` on that match `pred`. */
function requestsSince(capture, since, pred) {
	return capture.frames.slice(since).filter((f) => f.dir === 'sent' && f.msg && f.msg.type === 'request' && pred(f.msg));
}

// ---------------------------------------------------------------------------
// The store's side, through the TypeScript client (never through the page)
// ---------------------------------------------------------------------------

function storeClient(base) {
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
	/** The running tasks (the task list the SDKs read, `rrext_get_tasks`). */
	async function runningTasks() {
		const client = await server();
		const body = await client.call('rrext_get_tasks');
		return (body && body.tasks) || [];
	}
	async function tokenOf(fixture, source) {
		const tasks = await runningTasks();
		const row = tasks.find((t) => (t.pipeline || {}).project_id === fixture.projectId && t.source === source);
		if (!row) throw new Error(`${fixture.name} / ${source} is not running (start_fixtures.py)`);
		return row.token;
	}
	/** A tool call on `nodeId` through the fixture's Tools task. */
	async function tool(fixture, name, input = {}, nodeId = 'store_1') {
		const client = await server();
		return client.tool({ token: await tokenOf(fixture, 'tools_1'), tool: name, nodeId, input, timeout: 60000 });
	}
	/** dialect.dimension of the fixture's managed store (null when it does not say). */
	async function dimension(fixture) {
		const answer = await tool(fixture, 'dialect');
		return answer && Number.isInteger(answer.dimension) && answer.dimension > 0 ? answer.dimension : null;
	}
	async function close() {
		if (sdk) await sdk.disconnect().catch(() => {});
	}
	return { server, runningTasks, tokenOf, tool, dimension, close };
}

// ---------------------------------------------------------------------------
// Page helpers
// ---------------------------------------------------------------------------

async function bodyText(page) {
	const text = await page.locator('body').innerText();
	return typeof text === 'string' ? text : '';
}

/** Click a view switch ("Console", "Map") or a panel tab: a tab, or a button where the app uses buttons. */
async function switchView(page, name) {
	const tab = page.getByRole('tab', { name }).first();
	if (await tab.isVisible().catch(() => false)) return tab.click();
	return page.getByRole('button', { name }).first().click();
}

async function focusedText(page) {
	const text = await page.evaluate(() => (document.activeElement ? document.activeElement.textContent || '' : ''));
	return typeof text === 'string' ? text : '';
}

/** An attribute as an integer; null when absent, empty or not a plain integer. */
async function attrInt(locator, name) {
	const v = await locator.getAttribute(name).catch(() => null);
	return typeof v === 'string' && /^-?\d+$/.test(v.trim()) ? Number(v.trim()) : null;
}

/** An attribute as a number; null when absent, empty or not a number. */
async function attrNum(locator, name) {
	const v = await locator.getAttribute(name).catch(() => null);
	return typeof v === 'string' && /^-?\d+(\.\d+)?(e-?\d+)?$/i.test(v.trim()) ? Number(v.trim()) : null;
}

/** An attribute as a string; null when absent. */
async function attrText(locator, name) {
	const v = await locator.getAttribute(name).catch(() => null);
	return typeof v === 'string' ? v : null;
}

/** A locator's text, '' when there is none. */
async function textOf(locator) {
	const v = await locator.innerText().catch(() => '');
	return typeof v === 'string' ? v : '';
}

/** From the connections landing: open a fixture's connection on its console. */
async function openConnection(page, fixture) {
	const launcher = page.getByRole('button', { name: CONSOLE.launcher });
	if (await launcher.isVisible().catch(() => false)) await launcher.click();
	await page.getByText(fixture.name).first().click();
	for (const name of CONSOLE.openConsole) {
		const button = page.getByRole('button', { name }).first();
		if (await button.isVisible().catch(() => false)) {
			await button.click();
			break;
		}
	}
	await page.getByText(CONSOLE.statsDocuments).first().waitFor({ timeout: 60000 });
}

module.exports = {
	sleep,
	createRecorder,
	objectId,
	makePdf,
	fullVectors,
	toolOf,
	nodeOf,
	isUpload,
	sameVector,
	privacyViolations,
	captureFrames,
	exchanges,
	waitForExchange,
	requestsSince,
	storeClient,
	bodyText,
	switchView,
	focusedText,
	attrInt,
	attrNum,
	attrText,
	textOf,
	openConnection,
};
