// =============================================================================
// MIT License
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

// =============================================================================
// IDENTITY SCOPE — a change of account closes the previous account's tabs
// =============================================================================
//
// GX-FE-17. When the signed-in user, organization or team changes without a
// reload (or the user signs out), the endpoint store forgets every connection.
// Open query, table, designer, diagram and workbench tabs, and the schema
// snapshots, belonged to the previous account and must go with it, so its
// query results are never shown to the next one.
//
// The tabs are checked against the shell's REAL document model (it needs only
// React), so a closed editor is proven gone from its group and its document
// released. SqlApp has no DOM harness here, so its wiring is checked against
// the source, as the QueryView wiring tests do.
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import type { RocketRideClient } from 'shell';
import { Documents } from '../../../packages/shell/src/components/docs/Documents';
import { CONNECTIONS_URI, closeConnectionDocuments, connectionUri, designUri, diagramUri, nextQueryDoc, tableDataUri } from '../src/docs';
import { createIdentityScope, forgetConnectionScope, sqlIdentityScope } from '../src/identityScope';
import { getSession, refreshSchema, schemaSnapshot } from '../src/schema/schemaStore';
import { registerEndpoint } from './support';

// =============================================================================
// HELPERS
// =============================================================================

/**
 * A document model holding the Connections landing plus one tab of every
 * connection-scoped kind for `key`, with the query tab also split into a
 * second group (so one document has two editors).
 *
 * @param key - The endpoint key the tabs belong to.
 * @returns The document model.
 */
function docsWithEveryTab(key: string): Documents {
	const docs = new Documents();
	docs.openStaticDocument(CONNECTIONS_URI, 'Connections');
	docs.openStaticDocument(connectionUri(key), 'Orders DB', { key });
	docs.openStaticDocument(tableDataUri(key, 'odd:name'), 'odd:name', { key });
	docs.openStaticDocument(designUri(key, null), 'New table', { key });
	docs.openStaticDocument(diagramUri(key), 'Diagram', { key });
	const query = nextQueryDoc(key);
	docs.openStaticDocument(query.uri, query.label, { key });
	docs.splitGroupWithDocument(docs.getState().activeGroupId, 'horizontal');
	return docs;
}

/**
 * The document URIs the model still has an editor for.
 *
 * @param docs - The document model.
 * @returns The URIs, sorted.
 */
function openUris(docs: Documents): string[] {
	return Object.values(docs.getState().editors).map((editor) => editor.documentUri).sort();
}

/** A fake client whose tool calls wait until `release` is called. */
interface IGatedClient {
	client: RocketRideClient;
	/** Every tool invoked, in order. */
	tools: string[];
	/** Let every waiting (and later) call answer. */
	release(): void;
}

/**
 * Build a fake client that answers like a postgres node, but only once released.
 *
 * @param gated - Whether calls wait for `release` (false: answer at once).
 * @param database - The database name its schema reports.
 * @returns The client, its tool log and the release switch.
 */
function gatedClient(gated: boolean, database = 'previous_team_db'): IGatedClient {
	const tools: string[] = [];
	let open = !gated;
	const waiting: (() => void)[] = [];
	const client = {
		getTaskToken: async () => 'token-1',
		tool: async ({ tool }: { tool: string }) => {
			tools.push(tool);
			if (!open) await new Promise<void>((resolve) => waiting.push(resolve));
			if (tool === 'dialect') return { dialect: 'postgres' };
			return { database, tables: { orders: { columns: [] } } };
		},
	} as unknown as RocketRideClient;
	return {
		client,
		tools,
		release: () => {
			open = true;
			waiting.splice(0).forEach((resolve) => resolve());
		},
	};
}

// =============================================================================
// CLOSING THE TABS
// =============================================================================

describe('closeConnectionDocuments', () => {
	it('closes every connection-scoped tab in every group and keeps the Connections landing', () => {
		const docs = docsWithEveryTab('scope:tabs');
		assert.equal(Object.keys(docs.getState().groups).length, 2, 'the query tab is split into a second group');

		const closed = closeConnectionDocuments(docs);

		assert.equal(closed, 6, 'five documents, one of them in two groups');
		assert.deepEqual(openUris(docs), [CONNECTIONS_URI]);
		// The documents are released, not just hidden: nothing still holds the results.
		assert.deepEqual(Object.keys(docs.getState().documents), [CONNECTIONS_URI]);
		for (const group of Object.values(docs.getState().groups)) {
			for (const editorId of group.editorIds) assert.ok(docs.getState().editors[editorId], `group ${group.id} still lists a closed editor`);
		}
	});

	it('closes nothing when only the landing is open', () => {
		const docs = new Documents();
		docs.openStaticDocument(CONNECTIONS_URI, 'Connections');
		assert.equal(closeConnectionDocuments(docs), 0);
		assert.deepEqual(openUris(docs), [CONNECTIONS_URI]);
	});
});

// =============================================================================
// WHEN THE IDENTITY COUNTS AS CHANGED
// =============================================================================

describe('createIdentityScope', () => {
	/**
	 * A scope whose forget step is counted.
	 *
	 * @returns The scope and a read of how often it forgot.
	 */
	function countedScope(): { scope: ReturnType<typeof createIdentityScope>; forgets: () => number } {
		let count = 0;
		return { scope: createIdentityScope(() => { count += 1; }), forgets: () => count };
	}

	it('binds the first identity it sees without forgetting anything', () => {
		const { scope, forgets } = countedScope();
		assert.equal(scope.apply('u1|org-A|team-A'), false);
		assert.equal(forgets(), 0);
	});

	it('forgets when the user, organization or team changes', () => {
		const { scope, forgets } = countedScope();
		scope.apply('u1|org-A|team-A');
		assert.equal(scope.apply('u1|org-A|team-B'), true, 'team');
		assert.equal(scope.apply('u1|org-B|team-B'), true, 'organization');
		assert.equal(scope.apply('u2|org-B|team-B'), true, 'user');
		assert.equal(forgets(), 3);
	});

	it('forgets on sign-out, and again when somebody signs in', () => {
		const { scope, forgets } = countedScope();
		scope.apply('u1|org-A|team-A');
		assert.equal(scope.apply(null), true);
		assert.equal(scope.apply('u1|org-A|team-A'), true);
		assert.equal(forgets(), 2);
	});

	it('forgets nothing when the same identity arrives again (a token refresh, a new object)', () => {
		const { scope, forgets } = countedScope();
		scope.apply('u1|org-A|team-A');
		assert.equal(scope.apply('u1|org-A|team-A'), false);
		assert.equal(forgets(), 0);
	});
});

// =============================================================================
// WHAT IS FORGOTTEN
// =============================================================================

describe('forgetConnectionScope', () => {
	it('closes the connection tabs and drops the schema snapshots', async () => {
		const endpoint = await registerEndpoint('scope:forget');
		const { client } = gatedClient(false);
		await refreshSchema(client, endpoint);
		assert.equal(schemaSnapshot(endpoint.key).status, 'ready');
		const docs = docsWithEveryTab(endpoint.key);

		forgetConnectionScope(docs);

		assert.deepEqual(openUris(docs), [CONNECTIONS_URI]);
		assert.equal(schemaSnapshot(endpoint.key).status, 'idle');
		assert.equal(schemaSnapshot(endpoint.key).schema, null);
	});

	it('drops a schema read still in flight, so its late answer is not shown', async () => {
		const endpoint = await registerEndpoint('scope:in-flight');
		const gate = gatedClient(true);
		const pending = refreshSchema(gate.client, endpoint);
		assert.equal(schemaSnapshot(endpoint.key).status, 'loading');

		forgetConnectionScope(null);
		gate.release();
		await pending;

		assert.equal(schemaSnapshot(endpoint.key).status, 'idle');
		assert.equal(schemaSnapshot(endpoint.key).schema, null, 'the previous account\'s schema came back');
	});

	it('never starts a fresh read that was queued behind the dropped one', async () => {
		const endpoint = await registerEndpoint('scope:queued');
		const gate = gatedClient(true);
		const plain = refreshSchema(gate.client, endpoint);
		const queued = refreshSchema(gate.client, endpoint, { fresh: true });

		forgetConnectionScope(null);
		gate.release();
		await Promise.all([plain, queued]);

		assert.ok(!gate.tools.includes('refresh_schema'), 'the queued fresh read still ran for the previous account');
		assert.equal(schemaSnapshot(endpoint.key).status, 'idle');
	});

	it('runs the next read afresh instead of joining the dropped one', async () => {
		const endpoint = await registerEndpoint('scope:rejoin');
		const before = gatedClient(true);
		const dropped = refreshSchema(before.client, endpoint);
		forgetConnectionScope(null);

		const after = gatedClient(false, 'next_team_db');
		// Joining the dropped read would wait on it for ever; give up after a second.
		const settled = await Promise.race([
			refreshSchema(after.client, endpoint).then(() => 'answered'),
			new Promise<string>((resolve) => setTimeout(() => resolve('joined'), 1000)),
		]);
		assert.equal(settled, 'answered', 'the read after the change joined the dropped one');
		assert.ok(after.tools.length > 0);
		assert.equal(schemaSnapshot(endpoint.key).schema?.database, 'next_team_db');

		before.release();
		await dropped;
		assert.equal(schemaSnapshot(endpoint.key).schema?.database, 'next_team_db', 'the dropped read overwrote the fresh one');
	});

	it('rebuilds the cached session instead of reusing the previous account\'s', async () => {
		const endpoint = await registerEndpoint('scope:session');
		const { client } = gatedClient(false);
		const first = getSession(client, endpoint);
		assert.equal(getSession(client, endpoint), first, 'sessions are cached per endpoint');

		forgetConnectionScope(null);

		assert.notEqual(getSession(client, endpoint), first);
	});
});

describe('sqlIdentityScope (the app\'s instance)', () => {
	it('drops the schema snapshots when the identity changes', async () => {
		const endpoint = await registerEndpoint('scope:app');
		const { client } = gatedClient(false);
		sqlIdentityScope.apply('u1|org-A|team-A');
		await refreshSchema(client, endpoint);
		assert.equal(schemaSnapshot(endpoint.key).status, 'ready');

		assert.equal(sqlIdentityScope.apply('u1|org-A|team-B'), true);

		assert.equal(schemaSnapshot(endpoint.key).status, 'idle');
	});
});

// =============================================================================
// SQLAPP WIRING
// =============================================================================

describe('SqlApp: an identity change reaches the scope', () => {
	const source = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'SqlApp.tsx'), 'utf8');
	const scopeSource = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'identityScope.ts'), 'utf8');

	it('derives the fingerprint from the identity prop the shell passes', () => {
		assert.match(source, /const fingerprint = identityFingerprint\(identityFromConnectResult\(identity\)\);/, 'SqlApp does not derive the identity fingerprint');
	});

	it('applies it before paint, on every fingerprint change', () => {
		assert.match(source, /useLayoutEffect\(\(\) => \{\s*sqlIdentityScope\.apply\(fingerprint\);\s*\}, \[fingerprint\]\);/, 'SqlApp does not apply the fingerprint to the identity scope');
	});

	it('closes the app\'s own document model when it forgets', () => {
		assert.match(scopeSource, /createIdentityScope\(\(\) => forgetConnectionScope\(getDocs\(\)\)\)/);
	});
});
