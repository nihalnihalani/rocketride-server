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
// VECTOR - THE CONSOLE MODEL (pure): what every panel and the map are handed
// =============================================================================
//
// One ConsoleModel per open connection, rebuilt by the console from the live
// endpoint, its probe and the last stats answer. Panels never change it; they
// ask the console (ConsoleActions). Each action carries whether it is
// available and, when it is not, the sentence the disabled control shows:
//
//   writes  the trash buttons: `dialect.allow_writes`, `capabilities.remove`,
//           not read-only, and the connection's calls ride on a Tools source.
//   ingest  the drop zone: an Ingest source is running, not read-only.
//   chat    the chat: a Chat source is running.
//   embed   text queries: an embedding node the anchor source reaches.
// =============================================================================

import type { IExplorerEndpoint, IProbeResult } from 'shared/explorer';
import type { Availability, ConsoleModel, IScopeState, VectorNodes } from '../contract/types';
import { DEFAULT_LIMITS, readDialect } from './results';
import type { IStatsView } from './results';
import { BUSY, CODE_SENTENCES, EMPTY } from './wording';

/** Available. */
const ON: Availability = { enabled: true, reason: null };

/**
 * Not available, and why.
 *
 * @param reason - The sentence the disabled control shows.
 * @returns The availability.
 */
function off(reason: string): Availability {
	return { enabled: false, reason };
}

/**
 * The nodes a connection uses: its store node, the embedding node its Tools
 * source controls (any embedding node on a read-only connection), and the
 * pipeline's LLM node, by id and display name. Read from the pipeline's
 * component list (ids, providers, names and control edges only).
 *
 * @param endpoint - The endpoint.
 * @returns The nodes.
 */
export function consoleNodes(endpoint: IExplorerEndpoint): VectorNodes {
	const components = endpoint.components ?? [];
	const toolsSource = endpoint.roles.tools?.source ?? null;
	const embedding = components.filter((c) => typeof c.provider === 'string' && c.provider.startsWith('embedding_'));
	const embed = toolsSource === null ? embedding[0] : embedding.find((c) => (c.control ?? []).some((edge) => edge.from === toolsSource));
	const llm = components.find((c) => typeof c.provider === 'string' && c.provider.startsWith('llm_'));
	return {
		store: endpoint.nodeId,
		embed: embed?.id ?? null,
		llm: llm?.id ?? null,
		llmName: llm ? (llm.name ?? llm.id ?? null) : null,
	};
}

/**
 * The names of the other store nodes this pipeline's Tools source controls
 * ("This pipeline's ingest also reaches: …").
 *
 * @param endpoint - The endpoint.
 * @param providers - The vector store providers.
 * @returns Their display names.
 */
export function alsoReaches(endpoint: IExplorerEndpoint, providers: ReadonlySet<string>): string[] {
	const toolsSource = endpoint.roles.tools?.source ?? null;
	if (toolsSource === null) return [];
	return (endpoint.components ?? [])
		.filter((c) => c.id !== endpoint.nodeId && typeof c.provider === 'string' && providers.has(c.provider) && (c.control ?? []).some((edge) => edge.from === toolsSource))
		.map((c) => c.name ?? c.id ?? '')
		.filter((name) => name !== '');
}

/**
 * Whether the source bound to the tools role is a Tools source by the
 * pipeline's component list (the store refuses removal from any other source,
 * so the trash is disabled up front). A source the list does not show is not
 * taken for one.
 *
 * @param endpoint - The endpoint.
 * @returns True when the bound source's component has the `tools` provider.
 */
export function toolsSourceIsTools(endpoint: IExplorerEndpoint): boolean {
	const source = endpoint.roles.tools?.source;
	if (!source) return false;
	return (endpoint.components ?? []).some((c) => c.id === source && c.provider === 'tools');
}

/**
 * What the console's remove controls get: the model's `writes`, disabled while a removal runs.
 *
 * @param writes - The model's writes.
 * @param removal - The controller's removal status.
 * @returns The availability the trash buttons and "Remove selected" use.
 */
export function writesDuringRemoval(writes: Availability, removal: 'idle' | 'running' | 'done' | 'error'): Availability {
	return removal === 'running' && writes.enabled ? off(BUSY.removing) : writes;
}

/**
 * The documents the next chat question is asked about: those of "Ask about
 * these" first, else the scope's while its Chat toggle is on and it resolved
 * to at least one document; never more than `limits.scope_keys_max` (above it
 * the chat is not scoped and the ScopeBar says why).
 *
 * @param asked - The documents "Ask about these" chose, or null.
 * @param scope - The console's scope, or null.
 * @param cap - `limits.scope_keys_max`.
 * @returns The objectIds, or null for the whole collection.
 */
export function chatScopeFor(asked: readonly string[] | null, scope: IScopeState | null | undefined, cap: number): readonly string[] | null {
	if (asked !== null && asked.length > 0) return asked.length <= cap ? asked : null;
	if (!scope || !scope.applyTo.chat || scope.overflow !== null || scope.objectIds === null || scope.objectIds.length === 0) return null;
	return scope.objectIds.length <= cap ? scope.objectIds : null;
}

/**
 * Build the console model of a connection.
 *
 * @param endpoint - The live endpoint.
 * @param probe - Its probe, or undefined before it answered.
 * @param stats - The last stats answer, or null.
 * @returns The model.
 */
export function buildConsoleModel(endpoint: IExplorerEndpoint, probe: IProbeResult | undefined, stats: IStatsView | null): ConsoleModel {
	const dialect = probe?.ok ? readDialect(probe.info) : null;
	const readOnly = endpoint.readOnly === true;
	const nodes = consoleNodes(endpoint);
	const toolsBound = Boolean(endpoint.roles.tools);

	let writes: Availability;
	if (readOnly || !toolsBound) writes = off(EMPTY.readOnly);
	else if (!toolsSourceIsTools(endpoint)) writes = off(CODE_SENTENCES.WRITES_SOURCE);
	else if (dialect === null) writes = off('The store node has not answered yet.');
	else if (!dialect.allow_writes) writes = off(CODE_SENTENCES.WRITES_DISABLED);
	else if (dialect.capabilities.remove !== true) writes = off("This store node cannot remove documents. Update the pipeline's store node to a version that supports Vector Explorer.");
	else writes = ON;

	let ingest: Availability;
	if (readOnly) ingest = off(EMPTY.readOnly);
	else if (!endpoint.roles.ingest) ingest = off(EMPTY.noIngest);
	else ingest = ON;

	const chat = endpoint.roles.chat ? ON : off(EMPTY.noChat);
	const embed = nodes.embed !== null && (toolsBound || Boolean(endpoint.roles.chat)) ? ON : off(EMPTY.noEmbed);

	return {
		connectionKey: endpoint.key,
		connection: { endpoint, dialect },
		nodes,
		collection: dialect?.collection ?? null,
		stats: stats === null ? null : toStatsResult(stats),
		limits: dialect?.limits ?? { ...DEFAULT_LIMITS },
		capabilities: dialect?.capabilities ?? {},
		writes,
		ingest,
		chat,
		embed,
		readOnly,
	};
}

/**
 * The stats view back in the wire shape the contract's ConsoleModel carries.
 *
 * @param view - The view.
 * @returns The answer as the node would send it (nulls where it did not count).
 */
function toStatsResult(view: IStatsView): NonNullable<ConsoleModel['stats']> {
	return {
		success: true,
		count: view.legacyCount ?? 0,
		model: view.model ?? '',
		vector_size: view.dimension ?? 0,
		collection_exists: view.collectionExists,
		documents: view.documents,
		documents_without_first_chunk: view.withoutFirstChunk,
		chunks: view.chunks,
		deleted_chunks: view.deleted,
		raw_count: view.rawCount,
		tables: view.tables,
		avg_chunks_per_document: view.avgPerDocument,
		dimension: view.dimension,
		metric: view.metric,
		computed_at: view.computedAt,
		counts_as_of: view.countsAsOf,
		caveats: view.caveats,
	};
}
