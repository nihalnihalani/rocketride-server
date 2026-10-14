// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP VIEW: the Map tab itself, statically rendered (react-dom/server)
// =============================================================================
//
// Effects do not run in a static render, so nothing is sampled, laid out or
// drawn: these pin what the view shows for each state of a connection, from
// the props and the shared selection alone. A drawn sample is put in the
// selection store as the console's map tab would hold it, so the view renders
// its canvas, toolbar, legend and side panel over sample_demo_1000.json and the
// light 5,000-point fixture (the G1 check: data-points equals the points).
//
// The shell's building blocks (EmptyState, Button, Banner) exist only inside a
// running shell; scripts/stub-shell.cjs leaves them out, so this file gives the
// stub plain stand-ins that render their text.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { IRoleChannel } from 'shared/explorer';
import { createSelectionStore } from '../src/contract/bridge';
import type { ConsoleActions, ConsoleModel, IDialectResult, ISampleModel, VectorChannels } from '../src/contract/types';
import { MAP_UNAVAILABLE } from '../src/map/wording';
import { MapView } from '../src/views/MapView';
import { loadSample, modelOf } from './support/map.samples';

const shell = require('shell') as Record<string, unknown>;
shell.EmptyState ??= (p: { title: string; description?: string; action?: React.ReactNode }) => (
	<div data-empty-state="">
		<h3>{p.title}</h3>
		<p>{p.description}</p>
		{p.action}
	</div>
);
shell.Button ??= (p: { children?: React.ReactNode }) => <button type="button">{p.children}</button>;
shell.Banner ??= (p: { children?: React.ReactNode }) => <div role="alert">{p.children}</div>;

const FIX = path.resolve(__dirname, 'fixtures', 'provisional');
const dialect = JSON.parse(fs.readFileSync(path.join(FIX, 'dialect_pgvector.json'), 'utf8')) as IDialectResult;
const noop = (): void => undefined;
const KEY = 'conn-1';

/** A connection's console model over the pgvector dialect fixture. */
function modelWith(extra: Partial<ConsoleModel> = {}): ConsoleModel {
	const on = { enabled: true, reason: null };
	return {
		connectionKey: KEY,
		connection: { endpoint: {} as ConsoleModel['connection']['endpoint'], dialect },
		nodes: { store: 'store_1', embed: 'embed_1', llm: null, llmName: null },
		collection: dialect.collection,
		stats: null,
		limits: dialect.limits,
		capabilities: dialect.capabilities,
		writes: on,
		ingest: on,
		chat: on,
		embed: on,
		readOnly: false,
		...extra,
	};
}

/** A Tools channel that answers nothing (no effect runs in a static render). */
const tools = { invoke: () => new Promise<never>(() => undefined) } as unknown as IRoleChannel;
const channels: VectorChannels = { tools, chat: null, ingest: null };
const actions: ConsoleActions = { openDocument: noop, showOnMap: noop, requestRemove: noop, askAbout: noop, documentsChanged: noop, announce: noop };

/** The Map tab, statically rendered. */
function render(opts: { model?: ConsoleModel; channels?: VectorChannels; sample?: ISampleModel | null; selectionKey?: string } = {}): string {
	const selection = createSelectionStore(opts.selectionKey ?? KEY);
	if (opts.sample) selection.setSampleModel(opts.sample);
	return renderToStaticMarkup(<MapView model={opts.model ?? modelWith()} channels={opts.channels ?? channels} selection={selection} actions={actions} visible />);
}

/** The value of `attr` on the first element with class `cls`. */
function attrOf(out: string, cls: string, attr: string): string | null {
	const tag = new RegExp(`<[a-z]+[^>]*class="${cls}"[^>]*>`).exec(out);
	const m = tag ? new RegExp(`${attr}="([^"]*)"`).exec(tag[0]) : null;
	return m ? (m[1] as string) : null;
}

test('a store that cannot sample has no map, and says so (the console is unaffected)', () => {
	const out = render({ model: modelWith({ capabilities: { ...dialect.capabilities, sample: false } }) });
	assert.equal(attrOf(out, 'vector-map', 'data-map-state'), 'unavailable');
	assert.ok(out.includes(MAP_UNAVAILABLE));
	assert.doesNotMatch(out, /data-points=/);
});

test('no running source reaches the store: the map says which source to start', () => {
	const out = render({ channels: { tools: null, chat: null, ingest: null } });
	assert.equal(attrOf(out, 'vector-map', 'data-map-state'), 'unreachable');
	assert.match(out, /Start the pipeline&#x27;s Tools source \(or its Chat source\)/);
});

test('before the first sample: an empty state with "Draw sample" (the first open samples by itself once it is visible)', () => {
	const out = render();
	assert.equal(attrOf(out, 'vector-map', 'data-map-state'), 'empty');
	assert.match(out, /No sample drawn yet/);
	assert.match(out, /<button[^>]*>Draw sample<\/button>/);
	// A sample of another connection is not this map's.
	const other = render({ sample: modelOf(loadSample('sample_demo_1000.json')), selectionKey: 'conn-2' });
	assert.equal(attrOf(other, 'vector-map', 'data-map-state'), 'empty');
});

test('with sample_demo_1000.json drawn: the canvas has data-points 1000 on PCA, the toolbar, legend and Point tab around it', () => {
	const out = render({ sample: modelOf(loadSample('sample_demo_1000.json')) });
	assert.equal(attrOf(out, 'vector-map', 'data-map-state'), 'ready');
	assert.equal(attrOf(out, 'vector-map', 'data-sample-mode'), 'detailed');
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-points'), '1000');
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-mode'), 'detailed');
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-layout'), 'pca');
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-selection'), '');
	assert.match(out, /role="toolbar" aria-label="Map controls"/);
	assert.match(out, /of 1,318 chunks · 42 docs · seed 7/);
	assert.match(out, /aria-label="Map legend"/);
	assert.match(out, /Showing 1,000 of 1,318 chunks/);
	assert.match(out, /role="tab" aria-selected="true"[^>]*>Point</);
	assert.match(out, /Click a point or use the arrow keys/);
});

test('with the light 5,000-point fixture drawn: data-points 5000 in light mode, t-SNE refused with its reason, the placement note shown', () => {
	const out = render({ sample: modelOf(loadSample('sample_light_5000.json')) });
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-points'), '5000');
	assert.equal(attrOf(out, 'vector-map-canvas', 'data-mode'), 'light');
	assert.match(out, /<option value="tsne" disabled=""/);
	assert.match(out, /t-SNE is limited to 1,000 points; this sample has 5,000\./);
	assert.match(out, /Light sample: positions are rounded to 0\.01/);
});
