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
// ADAPTER - TYPED TOOL CALLS (pure: a session or a role channel goes in)
// =============================================================================
//
// Every call names its node (the store node, or the embedding node for
// `embed`) and unwraps the answer: a success comes back read by
// vector/results.ts, a failure envelope rejects as an ExplorerToolError of
// kind `store` that keeps its code. Writes go through `removeDocumentsBatch`
// only, once per batch, never retried (the tool table marks them so).
// =============================================================================

import type { IExplorerClient, IExplorerEndpoint, IEndpointStore, IInvokeOptions } from 'shared/explorer';
import type { IEmbedResult, VectorChannels } from '../contract/types';
import { readChunksPage, readDocumentsPage, readRemoveResult, readStats, unwrapEnvelope } from '../vector/results';
import type { IChunksPageView, IDocumentsPageView, IRemoveView, IStatsView } from '../vector/results';
import { TOOL } from './explorer';

/** What can call a tool: a session (the anchor token) or a role channel. */
export interface IVectorCaller {
	invoke<T = unknown>(tool: string, input?: Record<string, unknown>, opts?: IInvokeOptions): Promise<T>;
}

/**
 * Call one tool on one node and unwrap its answer.
 *
 * @param caller - A session or a role channel.
 * @param nodeId - The node (always named; a role channel requires it).
 * @param tool - The tool.
 * @param input - Its input.
 * @param opts - Per-call options (generation ticket, timeout).
 * @returns The success answer.
 */
export async function callVector<T = Record<string, unknown>>(caller: IVectorCaller, nodeId: string, tool: string, input: Record<string, unknown> = {}, opts: IInvokeOptions = {}): Promise<T> {
	const value = await caller.invoke<unknown>(tool, input, { ...opts, nodeId });
	return unwrapEnvelope<T>(tool, value);
}

/**
 * `stats` in full or quick mode.
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param mode - 'full' recomputes the counts; 'quick' answers the cached ones.
 * @param opts - Per-call options.
 * @returns The figures.
 */
export async function fetchStats(caller: IVectorCaller, nodeId: string, mode: 'full' | 'quick', opts: IInvokeOptions = {}): Promise<IStatsView> {
	return readStats(await callVector(caller, nodeId, TOOL.stats, { mode }, opts));
}

/**
 * One page of `documents` (active documents, path order).
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param page - The cursor (null for the first page) and the page size.
 * @param opts - Per-call options.
 * @returns The page.
 */
export async function fetchDocumentsPage(caller: IVectorCaller, nodeId: string, page: { cursor: string | null; limit: number }, opts: IInvokeOptions = {}): Promise<IDocumentsPageView> {
	return readDocumentsPage(await callVector(caller, nodeId, TOOL.documents, { cursor: page.cursor, limit: page.limit, deleted: 'active', sort: 'path' }, opts));
}

/**
 * One page of a document's chunks, in reading order.
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param page - The objectId, the last chunk id already listed (-1 for the start), the page size and which rows.
 * @param opts - Per-call options.
 * @returns The page.
 */
export async function fetchChunks(caller: IVectorCaller, nodeId: string, page: { objectId: string; afterChunk: number; limit: number; deleted?: 'active' | 'all' }, opts: IInvokeOptions = {}): Promise<IChunksPageView> {
	return readChunksPage(await callVector(caller, nodeId, TOOL.chunks, { object_id: page.objectId, after_chunk: page.afterChunk, limit: page.limit, deleted: page.deleted ?? 'active' }, opts));
}

/**
 * The existence probe: whether a document is stored and, when the store
 * counted them, how many chunks it has.
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param objectId - The objectId.
 * @returns `{ chunks }` when stored (`chunks` null when the store gave no total and has more than the one chunk asked for), or null for NOT_FOUND.
 */
export async function chunkCount(caller: IVectorCaller, nodeId: string, objectId: string): Promise<{ chunks: number | null } | null> {
	try {
		const page = readChunksPage(await callVector(caller, nodeId, TOOL.chunks, { object_id: objectId, limit: 1 }));
		return { chunks: page.total ?? (page.hasMore ? null : page.items.length) };
	} catch (error) {
		if (error instanceof Error && (error as { code?: string }).code === 'NOT_FOUND') return null;
		throw error;
	}
}

/**
 * Remove one batch of documents (the gated write). Sent once; never retried.
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param objectIds - At most write_ids_max objectIds.
 * @returns What the node removed.
 */
export async function removeDocumentsBatch(caller: IVectorCaller, nodeId: string, objectIds: readonly string[]): Promise<IRemoveView> {
	return readRemoveResult(await callVector(caller, nodeId, TOOL.removeDocument, { object_ids: [...objectIds] }, { idempotent: false }));
}

/**
 * Embed query texts on the embedding node of the same task.
 *
 * @param caller - A session (anchor token) or a channel that reaches the embedding node.
 * @param embedNodeId - The embedding node (embed_1).
 * @param texts - 1 to 8 texts.
 * @returns The vectors.
 */
export async function embedTexts(caller: IVectorCaller, embedNodeId: string, texts: readonly string[]): Promise<IEmbedResult> {
	return callVector<IEmbedResult>(caller, embedNodeId, TOOL.embed, { texts: [...texts], kind: 'query' });
}

/**
 * The role channels of a connection: null for a role whose source is not running.
 *
 * @param store - The endpoint store.
 * @param client - The client.
 * @param endpoint - The connection.
 * @returns The channels.
 */
export function vectorChannels(store: Pick<IEndpointStore, 'channel'>, client: IExplorerClient, endpoint: IExplorerEndpoint): VectorChannels {
	const bound = (role: string) => (endpoint.roles[role] ? store.channel(client, endpoint, role) : null);
	return { tools: bound('tools'), chat: bound('chat'), ingest: bound('ingest') };
}

/**
 * One document's directory row (`documents` with `object_ids`), or null when it is not stored.
 *
 * @param caller - A session or channel.
 * @param nodeId - The store node.
 * @param objectId - The objectId.
 * @returns The row, or null.
 */
export async function fetchDocument(caller: IVectorCaller, nodeId: string, objectId: string): Promise<IDocumentsPageView['items'][number] | null> {
	const page = readDocumentsPage(await callVector(caller, nodeId, TOOL.documents, { cursor: null, limit: 1, object_ids: [objectId], deleted: 'all', sort: 'path' }));
	return page.items.find((item) => item.objectId === objectId) ?? null;
}
