// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CONNECTION CARDS AND EMPTY STATES
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { IExplorerEndpoint, IProbeResult } from 'shared/explorer';
import { fakeWorld, manualClock, row } from 'shared/explorer/connect/testing';
import { makeGraphEndpointStore } from '../src/adapters/explorer';
import { RECHECKING_TEXT, connectionView, emptyState, ownerText, surfaceGate, testResultText } from '../src/graph/connections';
import { fixture } from './support/builders';

function endpoint(over: Partial<IExplorerEndpoint> = {}): IExplorerEndpoint {
	return { key: 'k1|dev|user|u1|t1|p1|tools=tools_1|graph_1', legacyKey: null, projectId: 'p1', pipelineName: 'Social graph', runKind: 'dev', ownerKind: 'user', ownerId: 'u1', teamId: 't1', roles: { tools: { source: 'tools_1' } }, missingRoles: [], source: 'tools_1', nodeId: 'graph_1', nodeName: 'Neo4j', provider: 'graph_neo4j', state: 'ready', running: true, ...over };
}
const probeOf = (name: string): IProbeResult => ({ ok: true, info: fixture<Record<string, unknown>>(`dialect_${name}`), dialect: name });
const failed = (message: string): IProbeResult => ({ ok: false, info: null, dialect: null, error: { kind: 'raised', message } });

test('a ready current node shows engine, target, writes, owner and an honest read-boundary note', () => {
	const view = connectionView(endpoint(), probeOf('neo4j'));
	assert.equal(view.badge.label, 'Running');
	assert.equal(view.openable, true);
	assert.equal(view.blocked, null);
	const rows = Object.fromEntries(view.details.map((d) => [d.label, d.value]));
	assert.equal(rows.Engine, 'Neo4j 5.26.31 Community');
	assert.equal(rows.Target, 'database neo4j');
	assert.equal(rows.Writes, 'Off (browsing only)');
	assert.equal(rows.Run, 'development run, user u1 (team t1)');
	assert.ok(view.notes.some((n) => /read-only session, which is a routing hint and not access control/.test(n)));
	assert.ok(!JSON.stringify(view).toLowerCase().includes('password'));
});

test('writes are shown as allowed only when the node says execute is on', () => {
	const on = { ok: true, info: { ...fixture<Record<string, unknown>>('dialect_neo4j'), allow_execute: true }, dialect: 'neo4j' } satisfies IProbeResult;
	assert.equal(connectionView(endpoint(), on).details.find((d) => d.label === 'Writes')?.value, 'Allowed (execute is on for this node)');
});

test('an OLD node is badged Needs upgrade and cannot be opened; it is not shown as healthy', () => {
	const view = connectionView(endpoint(), probeOf('old_node'));
	assert.equal(view.badge.label, 'Needs upgrade');
	assert.equal(view.badge.variant, 'warning');
	assert.equal(view.openable, false);
	assert.match(view.blocked ?? '', /needs an upgrade/);
	assert.ok(view.notes.some((n) => /does not support read_query/.test(n)));
});

test('stopped, unreachable and inaccessible endpoints say why they cannot be opened', () => {
	assert.match(connectionView(endpoint({ state: 'stopped', running: false }), undefined).blocked ?? '', /stopped/);
	assert.match(connectionView(endpoint({ state: 'unreachable', stateDetail: 'Node graph_1 not found in pipeline' }), undefined).blocked ?? '', /not found in pipeline/);
	assert.match(connectionView(endpoint({ state: 'inaccessible' }), undefined).blocked ?? '', /not allowed to call/);
	for (const state of ['stopped', 'unreachable', 'inaccessible'] as const) assert.equal(connectionView(endpoint({ state }), undefined).openable, false);
	assert.equal(connectionView(endpoint({ state: 'probing' }), undefined).openable, false, 'not before the probe answered');
});

test('a ready endpoint whose probe failed is blocked with the node\'s first line', () => {
	const view = connectionView(endpoint(), failed('Unexpected node answer\nsecond line'));
	assert.equal(view.blocked, 'Unexpected node answer');
	assert.equal(view.openable, false);
});

test('a deployment is named as one and shows the owning team, not the selected organization', () => {
	assert.equal(ownerText(endpoint({ runKind: 'deploy', ownerKind: 'team', ownerId: 'team-9', teamId: 'team-9' })), 'deployment, team team-9');
	assert.equal(ownerText(endpoint({ runKind: 'deploy', ownerKind: 'user', ownerId: 'u7', teamId: '' })), 'deployment, user u7');
	assert.match(connectionView(endpoint({ runKind: 'deploy' }), undefined).address, /\(deployment\)$/);
});

test('empty states: loading, error, none running (cause unknown) and unreachable', () => {
	assert.equal(emptyState('idle', [], null)?.kind, 'loading');
	assert.equal(emptyState('loading', [], null)?.kind, 'loading');
	assert.equal(emptyState('error', [], 'getTasks failed')?.kind, 'error');
	const none = emptyState('ready', [], null);
	assert.equal(none?.kind, 'none-running');
	assert.match(none?.unknown ?? '', /does not appear in this list at all/);
	assert.ok(!/not provisioned|unprovisioned|does not exist/i.test(`${none?.title} ${none?.description}`), 'an empty list never claims the graph is missing');
	assert.equal(emptyState('ready', [endpoint({ state: 'unreachable' })], null)?.kind, 'unreachable');
	assert.equal(emptyState('ready', [endpoint({ state: 'stopped' }), endpoint({ key: 'b', state: 'inaccessible' })], null)?.kind, 'unreachable');
	assert.equal(emptyState('ready', [endpoint()], null), null, 'something is usable: nothing to say');
	assert.equal(emptyState('loading', [endpoint()], null), null, 'cached endpoints stay visible while refreshing');
});

// GX-FE-12, AGE-T11, GX-CT-12: the page had a "graph does not exist yet" state keyed on a probe's wording. The probe
// (`dialect`) never touches the database, and a graph that does not exist stops the node at pipeline start, so the
// node never appears here at all. Nothing a listed node answers can say a graph is missing, so the page never says it
// (and no longer reads probe text to decide what to claim).
test('the page never claims a graph does not exist: a node that cannot be used is unreachable, and a missing graph is named among the start-up failures it cannot see', () => {
	const e = endpoint({ state: 'unreachable', stateDetail: 'Graph "rocketride" does not exist' });
	const said = emptyState('ready', [e], null);
	assert.equal(said?.kind, 'unreachable');
	assert.doesNotMatch(`${said?.title} ${said?.description}`, /does not exist/);
	const none = emptyState('ready', [], null);
	assert.match(none?.unknown ?? '', /does not appear in this list at all/);
	assert.match(none?.unknown ?? '', /graph that does not exist/, 'a missing graph is one reason a node is not listed');
	assert.match(none?.unknown ?? '', /pipeline.s log/);
});

test('failed discovery keeps already discovered endpoints visible instead of an empty state', () => {
	assert.equal(emptyState('error', [endpoint()], 'refresh failed'), null);
});

test('a node that advertises read_query is not badged as needing an upgrade, and one that says false is', () => {
	const current = connectionView(endpoint(), probeOf('neo4j'));
	assert.equal(current.badge.label, 'Running');
	assert.equal(current.openable, true);
	assert.equal(connectionView(endpoint(), { ok: true, info: { dialect: 'neo4j', capabilities: { read_query: false } }, dialect: 'neo4j' }).badge.label, 'Needs upgrade');
});

// -----------------------------------------------------------------------------
// GX-FE-01: a re-probe must not take an open workbench away
// -----------------------------------------------------------------------------

test('an open workbench stays on screen while its connection is checked again (a restart elsewhere, a reconnect, Test connection), and running pauses until it answers', async () => {
	const dialect = fixture<Record<string, unknown>>('dialect_neo4j');
	let hold = false;
	let release: () => void = () => undefined;
	const world = fakeWorld([row({ pipeline: { project_id: 'proj-g', name: 'Graph pipeline', components: [{ id: 'graph_1', provider: 'graph_neo4j', name: 'Graph' }] } })], (call) => {
		if (call.tool === 'dialect') return hold ? new Promise((resolve) => { release = () => resolve(dialect); }) : dialect;
		return {};
	});
	const clock = manualClock();
	const store = makeGraphEndpointStore({ clock });
	await store.refresh(world.client);
	await clock.settle();
	const gate = (opened: boolean) => {
		const s = store.getState();
		const e = s.endpoints[0];
		return surfaceGate(connectionView(e, s.probes[e.key]), opened);
	};
	assert.deepEqual(gate(false), { mounted: true, paused: null }, 'a ready connection opens');

	// Any task restart (from ANY pipeline) and every shell reconnect ask for refresh({ reprobe: true }).
	hold = true;
	const reprobe = store.refresh(world.client, { reprobe: true });
	await clock.settle();
	assert.equal(store.getState().endpoints[0].state, 'probing', 'the store really is re-checking');
	const during = gate(true);
	assert.equal(during.mounted, true, 'the editor, results, graph and inspector stay mounted');
	assert.equal(during.paused, RECHECKING_TEXT, 'running pauses, and says why');
	assert.deepEqual(gate(false), { mounted: false, paused: null }, 'a document that never opened keeps its empty state');
	release();
	await reprobe;
	await clock.settle();
	assert.deepEqual(gate(true), { mounted: true, paused: null }, 'running resumes once the node answers');

	// The drawer's Test connection does the same.
	const test = store.probe(world.client, store.getState().endpoints[0].key);
	await clock.settle();
	assert.equal(gate(true).mounted, true);
	assert.equal(gate(true).paused, RECHECKING_TEXT);
	release();
	await test;
	assert.deepEqual(gate(true), { mounted: true, paused: null });
});

test('a stopped or blocked connection keeps an open surface but pauses it with the card\'s reason', () => {
	const stopped = surfaceGate(connectionView(endpoint({ state: 'stopped', running: false }), undefined), true);
	assert.equal(stopped.mounted, true);
	assert.match(stopped.paused ?? '', /stopped/);
	const upgrade = surfaceGate(connectionView(endpoint(), probeOf('old_node')), true);
	assert.equal(upgrade.mounted, true);
	assert.match(upgrade.paused ?? '', /needs an upgrade/);
});

// -----------------------------------------------------------------------------
// GX-FE-08: what Test connection says, and for which card
// -----------------------------------------------------------------------------

test('Test connection says "not tested" when nothing was sent, never that the node did not answer', () => {
	const skipped = testResultText(null);
	assert.equal(skipped.variant, 'warning');
	assert.match(skipped.text, /^Not tested: /);
	assert.doesNotMatch(skipped.text, /did not answer/);
	assert.deepEqual(testResultText(probeOf('neo4j')), { variant: 'info', text: 'The node answered.' });
	const failedProbe = testResultText(failed('connection refused'));
	assert.equal(failedProbe.variant, 'error');
	assert.match(failedProbe.text, /did not answer its identity probe/);
});
