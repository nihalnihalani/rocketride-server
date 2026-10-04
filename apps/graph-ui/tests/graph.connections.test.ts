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
import { connectionView, emptyState, ownerText } from '../src/graph/connections';
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

test('empty states: loading, error, none running (cause unknown), unreachable, and unprovisioned only on positive evidence', () => {
	assert.equal(emptyState('idle', [], {}, null)?.kind, 'loading');
	assert.equal(emptyState('loading', [], {}, null)?.kind, 'loading');
	assert.equal(emptyState('error', [], {}, 'getTasks failed')?.kind, 'error');
	const none = emptyState('ready', [], {}, null);
	assert.equal(none?.kind, 'none-running');
	assert.match(none?.unknown ?? '', /does not appear in this list at all/);
	assert.ok(!/not provisioned|unprovisioned|does not exist/i.test(`${none?.title} ${none?.description}`), 'an empty list never claims the graph is missing');
	assert.equal(emptyState('ready', [endpoint({ state: 'unreachable' })], {}, null)?.kind, 'unreachable');
	assert.equal(emptyState('ready', [endpoint({ state: 'stopped' }), endpoint({ key: 'b', state: 'inaccessible' })], {}, null)?.kind, 'unreachable');
	assert.equal(emptyState('ready', [endpoint()], {}, null), null, 'something is usable: nothing to say');
	assert.equal(emptyState('loading', [endpoint()], {}, null), null, 'cached endpoints stay visible while refreshing');
	const e = endpoint();
	const positive = emptyState('ready', [e], { [e.key]: failed('Graph "rocketride" does not exist\nCreate it first') }, null);
	assert.equal(positive?.kind, 'unprovisioned');
	assert.match(positive?.description ?? '', /Graph "rocketride" does not exist/);
	// A failure that merely mentions a graph does not count, nor does a healthy node among failures.
	assert.notEqual(emptyState('ready', [e], { [e.key]: failed('Connection refused while reading graph rocketride') }, null)?.kind, 'unprovisioned');
	const ok = endpoint({ key: 'ok' });
	assert.notEqual(emptyState('ready', [e, ok], { [e.key]: failed('graph x does not exist'), ok: probeOf('neo4j') }, null)?.kind, 'unprovisioned');
});

test('failed discovery keeps already discovered endpoints visible instead of an empty state', () => {
	assert.equal(emptyState('error', [endpoint()], {}, 'refresh failed'), null);
});
