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
// VECTOR-UI - CONSOLE VIEW (R2-R5, R9: the main screen of a connection)
// =============================================================================
//
// The default document of every connection. Across the top, the database
// summary (StatsStrip); on the left, every document by its path with its
// trash button and, under it, the selected document's chunks; on the right,
// adding documents above the chat. The Map is a second tab of the same
// document: both stay mounted (the map gets `visible` so its canvas sleeps
// while hidden), and every map action lands back here through the console's
// actions and the shared selection.
//
// The console's calls and their pacing live in its controller
// (vector/consoleStore.ts); this view renders the controller's snapshot and
// forwards clicks. Removal is confirmed by the app-level dialog host.
// =============================================================================

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Banner, Button, ContentHeader, EmptyState, ToggleGroup, useShellConnection } from 'shell';
import type { IExplorerEndpoint } from 'shared/explorer';
import { makeConsoleActions } from '../adapters/consoleActions';
import type { ConsoleTab } from '../adapters/connections';
import { VECTOR_PROVIDERS, announcer } from '../adapters/explorer';
import { useConnection, useLiveEndpoint, useVectorEndpoints } from '../adapters/react';
import ChatPanel from '../components/ChatPanel';
import ChunkList from '../components/ChunkList';
import DocumentDirectory from '../components/DocumentDirectory';
import IngestPanel from '../components/IngestPanel';
import StatsStrip from '../components/StatsStrip';
import { getDocs } from '../docs';
import { documentUri } from '../vector/addresses';
import { alsoReaches } from '../vector/consoleModel';
import { roleLine, vectorCardView } from '../vector/connections';
import { consoleColumns } from '../vector/layout';
import { providerTitle } from '../vector/support';
import { BUSY } from '../vector/wording';
import { styles } from '../styles';
import MapView from './MapView';

/** The console's two tabs. */
const TABS: Array<{ id: ConsoleTab; label: string }> = [
	{ id: 'console', label: 'Console' },
	{ id: 'map', label: 'Map' },
];

/** Props for the {@link ConsoleView} component. */
export interface IConsoleViewProps {
	/** The endpoint the document was opened with (the live one is looked up). */
	opened: IExplorerEndpoint;
	/** False while another document is the active tab. */
	active: boolean;
}

/**
 * Open one stored document's tab.
 *
 * @param endpoint - The connection.
 * @param objectId - The document.
 * @param path - Its path, when known.
 * @param chunkId - A chunk to scroll to.
 */
export function openDocumentTab(endpoint: IExplorerEndpoint, objectId: string, path: string | null, chunkId?: number): void {
	const name = path ? (path.split(/[\\/]/).pop() ?? path) : objectId.slice(0, 8);
	getDocs()?.openStaticDocument(documentUri(endpoint.key, objectId), name, { endpoint, objectId, path, ...(chunkId === undefined ? {} : { chunkId }) });
}

/**
 * The console.
 *
 * @param props - {@link IConsoleViewProps}.
 * @returns The view.
 */
export const ConsoleView: React.FC<IConsoleViewProps> = ({ opened, active }) => {
	const { client } = useShellConnection();
	const endpoint = useLiveEndpoint(opened);
	const { probes } = useVectorEndpoints();
	const probe = probes[endpoint.key];
	const { entry, console: state, selection, tab, chatScope, model, channels } = useConnection(endpoint, client);
	const card = vectorCardView(endpoint, probe);
	const dialect = model.connection.dialect;

	// First load once the store node answered as a vector store; later loads are the controller's.
	useEffect(() => {
		if (card.openable && !entry.opened) {
			entry.opened = true;
			entry.controller.open();
		}
	}, [card.openable, entry]);
	// Hidden (another tab, another document): no quick stats, and the directory pauses.
	useEffect(() => {
		entry.controller.setVisible(active);
	}, [active, entry]);
	useEffect(() => {
		entry.controller.setWritesEnabled(model.writes.enabled);
	}, [model.writes.enabled, entry]);
	// A document selected elsewhere (the map, the chat's sources) lists its chunks here.
	const selectedId = selection.document?.objectId ?? null;
	useEffect(() => {
		if (selectedId !== state.chunks.objectId) entry.controller.selectDocument(selectedId);
	}, [selectedId, state.chunks.objectId, entry]);

	const actions = useMemo(
		() =>
			makeConsoleActions(entry, {
				openDocument: (objectId, chunkId) => {
					const row = entry.controller.getState().directory.rows.find((r) => r.objectId === objectId);
					openDocumentTab(entry.ctx.endpoint, objectId, row?.path ?? null, chunkId);
				},
				announce: (text) => announcer.announce(text),
			}),
		[entry]
	);

	// Stack the panels below the layout's breakpoint.
	const body = useRef<HTMLDivElement>(null);
	const [width, setWidth] = useState(0);
	useEffect(() => {
		const el = body.current;
		if (!el || typeof ResizeObserver === 'undefined') return undefined;
		const observer = new ResizeObserver(() => {
			if (el.clientWidth > 0) setWidth(el.clientWidth);
		});
		observer.observe(el);
		return () => observer.disconnect();
	}, []);
	const cols = consoleColumns(width);

	const title = `${providerTitle(endpoint.provider)}${model.collection ? ` · ${model.collection}` : ''}`;
	const subtitle = `"${endpoint.pipelineName}" · ${endpoint.nodeName || endpoint.nodeId} · ${roleLine(endpoint)}`;
	const refreshing = state.stats.status === 'loading';

	return (
		<div style={styles.root} data-console={endpoint.nodeId}>
			<ContentHeader
				title={title}
				subtitle={subtitle}
				actions={
					<>
						<ToggleGroup small options={TABS} value={tab} onChange={(id) => entry.tab.set(id)} />
						<Button variant="ghost" disabled={!card.openable || !entry.opened} onClick={() => entry.controller.refresh()}>
							{refreshing ? BUSY.refreshing : 'Refresh'}
						</Button>
					</>
				}
			/>
			{card.blocked && (
				<div style={{ padding: '8px 24px 0' }}>
					<Banner variant={endpoint.state === 'ready' ? 'warning' : 'info'}>{card.blocked}</Banner>
				</div>
			)}
			<StatsStrip stats={state.stats} dialect={dialect} readOnly={model.readOnly} />
			{state.removal.message && (
				<div role="status" style={{ ...styles.small, padding: '6px 24px' }}>
					{state.removal.status === 'running' ? BUSY.removing : state.removal.message}
				</div>
			)}
			<div ref={body} style={{ flex: 1, minHeight: 0, display: tab === 'console' ? 'flex' : 'none', flexDirection: cols.stacked ? 'column' : 'row', gap: 12, padding: 12, overflow: cols.stacked ? 'auto' : 'hidden' }}>
				<div style={{ flex: cols.stacked ? 'none' : `0 0 ${cols.left}`, height: cols.stacked ? 520 : undefined, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
					<DocumentDirectory pager={state.directory} selectedId={selectedId} writes={model.writes} onSelect={(item) => entry.selection.selectDocument({ objectId: item.objectId, path: item.path })} onRemove={(targets) => entry.controller.requestRemove(targets)} onLoadMore={() => entry.controller.loadMoreDocuments()} onRetry={() => entry.controller.retryDocuments()} />
					<ChunkList chunks={state.chunks} path={selection.document?.path ?? null} onMore={() => entry.controller.loadMoreChunks()} onOpen={(chunkId) => actions.openDocument(state.chunks.objectId ?? '', chunkId)} onMap={(key) => actions.showOnMap([key], 'document')} />
				</div>
				<div style={{ flex: cols.stacked ? 'none' : `1 1 ${cols.right}`, display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, minHeight: 0 }}>
					<div style={{ flex: cols.stacked ? 'none' : `0 0 ${cols.ingest}`, minHeight: cols.stacked ? 260 : 0, display: 'flex', flexDirection: 'column', overflow: 'auto' }} aria-label="Add documents" role="region">
						{model.ingest.enabled ? <IngestPanel model={model} channels={channels} actions={actions} alsoReaches={alsoReaches(endpoint, VECTOR_PROVIDERS)} /> : <EmptyState title="Add documents" description={model.ingest.reason ?? undefined} />}
					</div>
					<div style={{ flex: cols.stacked ? 'none' : `1 1 ${cols.chat}`, minHeight: cols.stacked ? 360 : 0, display: 'flex', flexDirection: 'column', overflow: 'auto' }} aria-label="Chat" role="region">
						{model.chat.enabled ? <ChatPanel model={model} channels={channels} selection={entry.selection} actions={actions} scope={chatScope} onClearScope={() => entry.chatScope.set(null)} /> : <EmptyState title="Chat" description={model.chat.reason ?? undefined} />}
					</div>
				</div>
			</div>
			<div style={{ flex: 1, minHeight: 0, display: tab === 'map' ? 'flex' : 'none', flexDirection: 'column', padding: 12 }}>
				<MapView model={model} channels={channels} selection={entry.selection} actions={actions} visible={active && tab === 'map'} />
			</div>
		</div>
	);
};

export default ConsoleView;
