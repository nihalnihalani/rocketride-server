// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CONSOLE MOUNTS: the console's own additive panels, in their hosts
// =============================================================================
//
// Statically rendered (no effects run): the directory's filter row is the
// ScopeBar, whose first field is the path box and which keeps the header one
// row with no scope; the stats strip ends with a collapsed Charts disclosure
// holding the StatsCharts; a document tab holds its HealthPanel. A component
// still a placeholder says "Not built yet".
// =============================================================================

import assert from 'node:assert/strict';
import Module from 'node:module';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { IRoleChannel } from 'shared/explorer';
import type { ConsoleActions, ConsoleModel, IDialectResult, IDocumentItem, VectorChannels } from '../src/contract/types';
import { fixture } from './support/fixtures';

// The shell's building blocks exist only inside a running shell: plain stand-ins that render their text.
const shellStandIn = {
	commonStyles: new Proxy({}, { get: () => ({}) }),
	Banner: (p: { children?: React.ReactNode }) => <div role="alert">{p.children}</div>,
	Button: (p: { children?: React.ReactNode; disabled?: boolean }) => (
		<button type="button" disabled={p.disabled}>
			{p.children}
		</button>
	),
	BxTrash: () => <svg aria-hidden="true" />,
	ContentHeader: (p: { title: string; subtitle?: string; actions?: React.ReactNode }) => (
		<header>
			<h1>{p.title}</h1>
			{p.subtitle ? <p>{p.subtitle}</p> : null}
			{p.actions}
		</header>
	),
	StatusBadge: (p: { children?: React.ReactNode; label?: string }) => <span>{p.children ?? p.label}</span>,
};
const moduleWithLoad = Module as unknown as { _load: (request: string, parent: unknown, isMain: boolean) => unknown };
const originalLoad = moduleWithLoad._load;
moduleWithLoad._load = function (request: string, parent: unknown, isMain: boolean): unknown {
	if (request === 'shell') return shellStandIn;
	return originalLoad.call(this, request, parent, isMain);
};

const { createSelectionStore } = require('../src/contract/bridge') as typeof import('../src/contract/bridge');
const { DocumentDirectory } = require('../src/components/DocumentDirectory') as typeof import('../src/components/DocumentDirectory');
const { StatsStrip } = require('../src/components/StatsStrip') as typeof import('../src/components/StatsStrip');
const { DocumentView } = require('../src/views/DocumentView') as typeof import('../src/views/DocumentView');
const { pagerApplyPage, pagerBegin, pagerInit } = require('../src/vector/documents') as typeof import('../src/vector/documents');
const { readDocumentsPage, readStats } = require('../src/vector/results') as typeof import('../src/vector/results');

const dialect = fixture<IDialectResult>('dialect_pgvector');
const noop = (): void => undefined;
const on = { enabled: true, reason: null };

/**
 * Assert a component's root is in a host's markup, and that it says "Not built yet" while it is a placeholder.
 *
 * @param html - The host's static markup.
 * @param name - The component.
 * @returns Where its root starts.
 */
function mounted(html: string, name: string): number {
	const at = html.search(new RegExp(`<[a-z]+[^>]*data-component="${name}"`));
	assert.ok(at >= 0, `${name} is mounted in its host`);
	if (html.slice(at, html.indexOf('>', at)).includes('data-placeholder')) assert.match(html.slice(at, at + 600), /Not built yet/, `${name} says it is not built yet`);
	return at;
}

test('the directory: the ScopeBar is its filter row, with the path box first, and nothing else between the title and the list', () => {
	const pager = pagerApplyPage(pagerBegin(pagerInit()), readDocumentsPage(fixture('documents_page1')));
	const html = renderToStaticMarkup(<DocumentDirectory pager={pager} selectedId={null} writes={on} onSelect={noop} onRemove={noop} onLoadMore={noop} onRetry={noop} />);
	const at = mounted(html, 'ScopeBar');
	const bar = html.slice(at, html.indexOf('</div>', at));
	assert.match(bar, /^<div[^>]*><input type="search" placeholder="Filter paths…" aria-label="Filter documents by path"/, 'the path box is its first field');
	assert.equal((html.match(/aria-label="Filter documents by path"/g) ?? []).length, 1, 'one path box');
	assert.ok(html.indexOf('data-component="ScopeBar"') < html.indexOf('aria-label="Stored documents"'));
});

test('the stats strip ends with a collapsed Charts disclosure holding the StatsCharts', () => {
	const rows: IDocumentItem[] = readDocumentsPage(fixture('documents_page1')).items;
	const stats = { view: readStats(fixture('stats_pgvector')), status: 'ready' as const, error: null, lastAt: 0, mode: 'full' as const };
	const html = renderToStaticMarkup(<StatsStrip stats={stats} dialect={dialect} readOnly={false} documents={rows} />);
	assert.match(html, /<details[^>]*><summary[^>]*>Charts<\/summary>/);
	assert.doesNotMatch(html, /<details[^>]* open/, 'collapsed by default');
	assert.ok(mounted(html, 'StatsCharts') > html.indexOf('>Charts</summary>'));
});

test('a document tab holds its HealthPanel', () => {
	const model: ConsoleModel = {
		connectionKey: 'doc-1',
		connection: { endpoint: { key: 'doc-1', nodeId: 'store_1', pipelineName: 'Vector demo', provider: 'postgres' } as ConsoleModel['connection']['endpoint'], dialect },
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
	};
	const tools = { invoke: () => new Promise<never>(() => undefined) } as unknown as IRoleChannel;
	const channels: VectorChannels = { tools, chat: null, ingest: null };
	const actions: ConsoleActions = { openDocument: noop, showOnMap: noop, requestRemove: noop, askAbout: noop, documentsChanged: noop, announce: noop };
	const html = renderToStaticMarkup(<DocumentView model={model} channels={channels} selection={createSelectionStore('doc-1')} actions={actions} objectId="75b89d86-a64e-5143-bf50-55d4a7fd8cd2" path="C:/demo/handbooks/falcon_handbook.md" />);
	assert.match(html, /data-document="75b89d86-a64e-5143-bf50-55d4a7fd8cd2"/);
	mounted(html, 'HealthPanel');
});
