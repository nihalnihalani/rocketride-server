// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// ADAPTER: the tool table, the probe, the endpoint store over VECTOR_ROLES, and the typed calls
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ExplorerToolError, VECTOR_ROLES, checkObject } from 'shared/explorer';
import { codedError, fakeWorld, manualClock, projectRows, ragComponents, vectorComponents } from 'shared/explorer/connect/testing';
import type { IFakeWorld, IToolCall } from 'shared/explorer/connect/testing';
import { DOC_SCHEMES, TOOL, VECTOR_PROVIDERS, VECTOR_TOOLS, WRITE_TOOLS, makeVectorEndpointStore, vectorNodeFilter, vectorProbe } from '../src/adapters/explorer';
import { callVector, chunkCount, embedTexts, fetchChunks, fetchDocumentsPage, fetchStats, removeDocumentsBatch, vectorChannels } from '../src/adapters/actions';
import { fixture } from './support/fixtures';

/** A world whose store answers like a pgvector node: dialect, stats, documents, chunks, remove. */
function world(rows = projectRows(['ingest_1', 'chat_1', 'tools_1'], vectorComponents('postgres')), over: Partial<Record<string, (call: IToolCall) => unknown>> = {}): IFakeWorld {
	return fakeWorld(rows, (call) => {
		const custom = over[call.tool];
		if (custom) return custom(call);
		switch (call.tool) {
			case 'dialect':
				return fixture('dialect_pgvector');
			case 'stats':
				return call.input?.mode === 'quick' ? fixture('stats_quick') : fixture('stats_pgvector');
			case 'documents':
				return call.input?.cursor ? fixture('documents_page2_last') : fixture('documents_page1');
			case 'chunks':
				return fixture('chunks_page');
			case 'remove_document':
				return fixture('remove_document_ok');
			case 'embed':
				return fixture('embed_ok');
			default:
				return { success: false, code: 'UNSUPPORTED', error: `no ${call.tool}` };
		}
	});
}

/** A store over a fake world with a manual clock, refreshed once. */
async function ready(w: IFakeWorld) {
	const clock = manualClock();
	const store = makeVectorEndpointStore({ clock, debounceMs: 0 });
	const refreshing = store.refresh(w.client);
	await clock.advance(0);
	await refreshing;
	await clock.settle();
	return { store, clock };
}

test('the tool table: reads idempotent and capability-gated, writes never replayed, every answer checked as an object only', () => {
	for (const [tool, spec] of Object.entries(VECTOR_TOOLS)) {
		assert.equal(spec.check, checkObject, `${tool}: a failure envelope passes the session and keeps its code`);
		assert.equal(spec.idempotent, !WRITE_TOOLS.has(tool), `${tool}: idempotent iff a read`);
	}
	assert.deepEqual([...WRITE_TOOLS].sort(), ['delete', 'remove_document', 'upsert']);
	assert.equal(VECTOR_TOOLS[TOOL.removeDocument].capability, 'remove');
	assert.equal(VECTOR_TOOLS[TOOL.documents].capability, 'documents');
	assert.equal(VECTOR_TOOLS[TOOL.sample].capability, 'sample');
	assert.equal(VECTOR_TOOLS[TOOL.stats].capability, undefined, 'stats is the legacy tool every node answers');
	assert.equal(VECTOR_TOOLS[TOOL.dialect].timeoutMs, 15_000);
	assert.deepEqual(DOC_SCHEMES, { bare: ['console'], suffixed: ['document'] });
	assert.equal(VECTOR_PROVIDERS.size, 9);
});

test('the probe: a dialect answer is ok; a failure envelope or a thrown error is not, and keeps its code', async () => {
	const answer = (value: unknown) => ({ endpoint: {} as never, info: () => null, invoke: async () => value }) as never;
	const ok = await vectorProbe(answer(fixture('dialect_pgvector')));
	assert.equal(ok.ok, true);
	assert.equal(ok.dialect, 'vector');
	const refused = await vectorProbe(answer(fixture('errors').STORE_ERROR));
	assert.deepEqual(refused, { ok: false, info: null, dialect: null, error: { kind: 'store', message: 'OperationalError: the store did not answer', code: 'STORE_ERROR' } });
	const thrower = {
		endpoint: {} as never,
		info: () => null,
		invoke: async () => {
			throw new ExplorerToolError({ kind: 'raised', tool: 'dialect', message: fixture('dialect_old_node').rejected.message });
		},
	} as never;
	const old = await vectorProbe(thrower);
	assert.equal(old.ok, false);
	assert.match(old.error?.message ?? '', /No handler found for tool "dialect"/);
	assert.equal(
		(
			await vectorProbe({
				endpoint: {} as never,
				info: () => null,
				invoke: async () => {
					throw new Error('boom');
				},
			} as never)
		).error?.kind,
		'raised'
	);
});

test('the node filter: with a Tools source only the stores it controls; without one, every store (read-only)', () => {
	const group = (toolsSource: string | null) => ({ toolsSource, anchorRole: toolsSource ? 'tools' : 'chat', boundRoles: [] });
	assert.equal(vectorNodeFilter({ id: 'store_1', control: [{ from: 'tools_1', classType: 'tool' }] }, group('tools_1')), true);
	assert.equal(vectorNodeFilter({ id: 'store_2' }, group('tools_1')), false, 'the chat path store is never a connection');
	assert.equal(vectorNodeFilter({ id: 'store_x', control: [{ from: 'tools_9', classType: 'tool' }] }, group('tools_1')), false);
	assert.equal(vectorNodeFilter({ id: 'store_1' }, group(null)), true);
});

test('discovery over the VX template: one connection, store_1, probed through the Tools token', async () => {
	const w = world();
	const { store } = await ready(w);
	const { endpoints, probes } = store.getState();
	assert.deepEqual(
		endpoints.map((e) => [e.nodeId, e.state, e.anchorRole, e.readOnly]),
		[['store_1', 'ready', 'tools', false]]
	);
	assert.equal(probes[endpoints[0].key].ok, true);
	const probe = w.calls.find((c) => c.tool === 'dialect')!;
	assert.equal(probe.nodeId, 'store_1');
	assert.match(probe.token, /_tools_1$/, 'the probe rides on the Tools source');
	assert.deepEqual(VECTOR_ROLES.readOnlyAnchors, ['chat', 'ingest']);
});

test('the typed calls: stats in full or quick mode, document pages, chunks, all on the store node', async () => {
	const w = world();
	const { store } = await ready(w);
	const endpoint = store.getState().endpoints[0];
	const session = store.session(w.client, endpoint);
	assert.equal((await fetchStats(session, endpoint.nodeId, 'full')).documents, 42);
	assert.equal((await fetchStats(session, endpoint.nodeId, 'quick')).countsAsOf, '2026-10-08T18:30:40Z');
	const page = await fetchDocumentsPage(session, endpoint.nodeId, { cursor: null, limit: 500 });
	assert.equal(page.items.length, 5);
	const next = await fetchDocumentsPage(session, endpoint.nodeId, { cursor: page.nextCursor, limit: 500 });
	assert.equal(next.nextCursor, null);
	const chunks = await fetchChunks(session, endpoint.nodeId, { objectId: 'kestrel', afterChunk: -1, limit: 100 });
	assert.equal(chunks.items.length, 3);
	const sent = w.calls.filter((c) => c.tool !== 'dialect').map((c) => [c.tool, c.nodeId, c.input]);
	assert.deepEqual(sent, [
		['stats', 'store_1', { mode: 'full' }],
		['stats', 'store_1', { mode: 'quick' }],
		['documents', 'store_1', { cursor: null, limit: 500, deleted: 'active', sort: 'path' }],
		['documents', 'store_1', { cursor: page.nextCursor, limit: 500, deleted: 'active', sort: 'path' }],
		['chunks', 'store_1', { object_id: 'kestrel', after_chunk: -1, limit: 100, deleted: 'active' }],
	]);
});

test('a failure envelope rejects with its code; the existence probe reads NOT_FOUND as "not stored" and never claims a count the node did not give', async () => {
	const probe = fixture('chunks_exists_probe');
	const answers: Record<string, unknown> = {
		missing: fixture('chunks_not_found'),
		report: probe,
		uncounted: { ...probe, total: null, has_more: true },
		single: { ...probe, total: null, has_more: false },
	};
	const w = world(undefined, {
		stats: () => fixture('errors').STORE_ERROR,
		chunks: (call) => answers[String(call.input?.object_id)],
	});
	const { store } = await ready(w);
	const endpoint = store.getState().endpoints[0];
	const session = store.session(w.client, endpoint);
	await assert.rejects(fetchStats(session, endpoint.nodeId, 'full'), (error: ExplorerToolError) => error.kind === 'store' && error.code === 'STORE_ERROR');
	assert.equal(await chunkCount(session, endpoint.nodeId, 'missing'), null);
	assert.deepEqual(await chunkCount(session, endpoint.nodeId, 'report'), { chunks: 19 });
	assert.deepEqual(await chunkCount(session, endpoint.nodeId, 'uncounted'), { chunks: null }, 'stored, but the store did not count its chunks');
	assert.deepEqual(await chunkCount(session, endpoint.nodeId, 'single'), { chunks: 1 }, 'one chunk and no more: that is the count');
	assert.deepEqual(
		w.calls.filter((c) => c.tool === 'chunks').map((c) => c.input),
		[
			{ object_id: 'missing', limit: 1 },
			{ object_id: 'report', limit: 1 },
			{ object_id: 'uncounted', limit: 1 },
			{ object_id: 'single', limit: 1 },
		]
	);
});

test('remove_document is sent once, even when the task is restarting, and reports what the node removed', async () => {
	let attempts = 0;
	const w = world(undefined, {
		remove_document: () => {
			attempts += 1;
			throw codedError('Task is not running', 'TASK_STOPPED');
		},
	});
	const { store } = await ready(w);
	const endpoint = store.getState().endpoints[0];
	await assert.rejects(removeDocumentsBatch(store.session(w.client, endpoint), endpoint.nodeId, ['a']), (error: ExplorerToolError) => error.code === 'TASK_STOPPED');
	assert.equal(attempts, 1, 'a write is never replayed');
	const ok = world();
	const { store: s2 } = await ready(ok);
	const e2 = s2.getState().endpoints[0];
	const view = await removeDocumentsBatch(s2.session(ok.client, e2), e2.nodeId, ['kestrel']);
	assert.equal(view.removedChunks, 12);
	assert.deepEqual(
		ok.calls.filter((c) => c.tool === 'remove_document').map((c) => [c.nodeId, c.input]),
		[['store_1', { object_ids: ['kestrel'] }]]
	);
});

test('embed goes to the embedding node of the same task, through the anchor token', async () => {
	const w = world();
	const { store } = await ready(w);
	const endpoint = store.getState().endpoints[0];
	const result = await embedTexts(store.session(w.client, endpoint), 'embed_1', ['where does the water come from?']);
	assert.equal(result.dimension, fixture('embed_ok').dimension);
	const call = w.calls.find((c) => c.tool === 'embed')!;
	assert.equal(call.nodeId, 'embed_1');
	assert.deepEqual(call.input, { texts: ['where does the water come from?'], kind: 'query' });
	assert.match(call.token, /_tools_1$/);
});

test('a stock RAG pipeline (webhook + chat, no Tools source) is a read-only connection anchored on chat', async () => {
	const w = world(projectRows(['webhook_1', 'chat_1'], ragComponents('postgres')));
	const { store } = await ready(w);
	const [endpoint] = store.getState().endpoints;
	assert.equal(endpoint.readOnly, true);
	assert.equal(endpoint.anchorRole, 'chat');
	const channels = vectorChannels(store, w.client, endpoint);
	assert.equal(channels.tools, null, 'no Tools channel without a Tools source');
	assert.ok(channels.chat);
	assert.ok(channels.ingest, 'the webhook fills the ingest role');
	await fetchStats(store.session(w.client, endpoint), endpoint.nodeId, 'full');
	assert.match(w.calls.filter((c) => c.tool === 'stats')[0].token, /_chat_1$/, 'a read-only card reads through its chat source');
});

test('callVector passes the node id and unwraps the envelope for a session or a role channel alike', async () => {
	const w = world();
	const { store } = await ready(w);
	const endpoint = store.getState().endpoints[0];
	const channels = vectorChannels(store, w.client, endpoint);
	assert.ok(channels.tools && channels.chat && channels.ingest);
	const viaChannel = await callVector<Record<string, unknown>>(channels.tools, endpoint.nodeId, 'stats', { mode: 'full' });
	assert.equal(viaChannel.documents, 42);
	await assert.rejects(callVector(channels.tools, endpoint.nodeId, 'vectors', { keys: [] }), (error: ExplorerToolError) => error.code === 'UNSUPPORTED');
});
