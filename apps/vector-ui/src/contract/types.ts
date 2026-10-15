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
// VECTOR-UI — CONTRACT TYPES (frozen; the seam between the console, map and chat/ingest code)
// =============================================================================
//
// Two halves:
//
//   1. WIRE TYPES — the JSON every vector store tool answers with, exactly as
//      docs/development/nodes/vector-tool-contract.md section 4 defines it. The
//      node is the source of truth; these types are what the app may rely on.
//      Keys the node may omit (older nodes, legacy answers) are optional.
//   2. APP TYPES — what the console hands its panels and the map: the
//      connection model, the role channels, the shared selection, and the props
//      of every component one part of the app renders for another.
//
// TYPES AND CONSTANTS ONLY: this module imports nothing at run time, so every
// node:test suite can import it. Raw vectors appear in exactly two wire types
// (IVectorItem.values and IEmbedResult.vectors); nothing under src/map ever
// receives either.
//
// A change to anything exported here is a lead decision broadcast to every
// lane the same day. Exception: the props of components rendered only inside
// another component of the same lane (marked "lane-internal") may be extended
// by that lane with optional fields.
// =============================================================================

import type { IExplorerEndpoint, IRoleChannel } from 'shared/explorer';

// =============================================================================
// 1. WIRE TYPES
// =============================================================================

// -----------------------------------------------------------------------------
// Vocabularies (mirror packages/ai/src/ai/common/store/vx_types.py)
// -----------------------------------------------------------------------------

/** Every `code` a failure envelope may carry. */
export const TOOL_CODES = [
	'INVALID_INPUT',
	'UNSUPPORTED',
	'NOT_FOUND',
	'RESERVED_ID',
	'COLLECTION_MISSING',
	'STORE_ERROR',
	'DIMENSION_MISMATCH',
	'MODEL_MISMATCH',
	'NO_EMBEDDER',
	'LIMIT_EXCEEDED',
	'SAMPLE_EXPIRED',
	'BUSY',
	'TIMEOUT',
	'RATE_LIMITED',
	'WRITES_DISABLED',
	'WRITES_SOURCE',
	'WRITES_PUBLIC',
	'WRITES_BROADCAST',
	'WRITES_AGENT',
	'WRITES_UNKNOWN_CALLER',
	'READS_PUBLIC',
] as const;

/** A documented failure code. */
export type ToolCode = (typeof TOOL_CODES)[number];

/** Every caveat a tool answer may carry. */
export const CAVEATS = [
	'brute_force_search',
	'no_filtered_count',
	'biased_sample',
	'score_scale_raw',
	'score_scale_inverted_fixed',
	'shared_org_table',
	'experimental',
	'cloud_only_unverified',
	'extras_not_stored',
	'documents_by_first_chunk',
	'document_count_capped',
	'documents_unsorted',
	'documents_paging_unsupported',
	'model_mismatch',
	'meta_column_pending',
	'filtered_search_may_underfill',
] as const;

/** A documented caveat. */
export type Caveat = (typeof CAVEATS)[number];

/** Boolean keys of `dialect.capabilities`. */
export const CAPABILITY_KEYS = [
	'describe',
	'count',
	'count_documents',
	'documents',
	'documents_distinct',
	'documents_sorted',
	'chunks',
	'vectors',
	'sample',
	'sample_light',
	'sample_stratified_native',
	'knn_native',
	'project',
	'neighbors',
	'search_vector',
	'search_keyword',
	'remove',
	'remove_count',
	'soft_delete',
	'embed_node',
] as const;

/** A boolean capability key. */
export type CapabilityKey = (typeof CAPABILITY_KEYS)[number];

/** Tools on a vector store node (bare names; the app always passes the node id). */
export const VECTOR_STORE_TOOLS = [
	'dialect',
	'stats',
	'documents',
	'chunks',
	'vectors',
	'sample',
	'project',
	'neighbors',
	'search',
	'remove_document',
	'delete',
	'upsert',
	'get',
	'objdir',
] as const;

/** A vector store tool name. */
export type VectorStoreTool = (typeof VECTOR_STORE_TOOLS)[number];

/** The tool on the embedding node (embed_1). */
export const EMBED_TOOL = 'embed';

/** objectId of the collection's control record: never listed, never removable. */
export const CONTROL_OBJECT_ID = 'schema';

/** `(objectId, chunkId)` — the logical key of a chunk on every backend. */
export type VectorKey = readonly [objectId: string, chunkId: number];

/** Which rows a listing covers. */
export type Deleted = 'active' | 'deleted' | 'all';

/** Similarity metric of a store. */
export type VectorMetric = 'cosine' | 'l2' | 'ip';

/** Backend family reported by `dialect.backend`. */
export type VectorBackend = 'pgvector' | 'qdrant' | 'chroma' | 'milvus' | 'weaviate' | 'pinecone' | 'astra' | 'atlas';

/** Support level reported by `dialect.support`. */
export type SupportLevel = 'supported' | 'experimental';

/** Sampling strategies (`sample.strategy`, `sample.strategy_used`). */
export type SampleStrategy = 'random' | 'stratified' | 'first';

/** Sample density: detailed (snippets, k ≤ 30, ≤ 2,000 points) or light (no text, k ≤ 10, ≤ 5,000 points). */
export type SampleMode = 'detailed' | 'light';

/** Who computed a kNN graph. */
export type KnnSource = 'native' | 'node';

// -----------------------------------------------------------------------------
// Envelope
// -----------------------------------------------------------------------------

/**
 * The failure envelope every tool answers with instead of raising. Extra keys
 * ride along for some codes (for example `retry_after_s` with RATE_LIMITED).
 * Older nodes answer legacy failures without `code`.
 */
export interface IToolFailure {
	success: false;
	/** A documented code; absent on legacy answers. */
	code?: ToolCode | string;
	/** A plain sentence. */
	error: string;
	detail?: string;
	/** Seconds until an embed call may be retried (RATE_LIMITED). */
	retry_after_s?: number;
	[extra: string]: unknown;
}

// -----------------------------------------------------------------------------
// dialect (the probe)
// -----------------------------------------------------------------------------

/** `dialect.capabilities`: the boolean keys plus the projections the node can compute. */
export type IVectorCapabilities = { [K in CapabilityKey]?: boolean } & {
	/** Projections the node computes (v1: ['pca']). */
	projection?: string[];
};

/** `dialect.limits`, enforced on the node; the app copies them for UX only. */
export interface IVectorLimits {
	documents_page: number;
	chunks_page: number;
	vectors_keys_max: number;
	sample_default: number;
	sample_max: number;
	sample_max_light: number;
	snippet_chars: number;
	knn_k_max: number;
	neighbors_k_max: number;
	project_keys_max: number;
	scope_keys_max: number;
	top_k_max: number;
	write_ids_max: number;
	sample_budget_ms: number;
	/** pgvector's statement deadline; null on backends without one. */
	statement_timeout_ms: number | null;
	counts_cached_s: number;
}

/** How a store computes `score`. */
export interface IScoreInfo {
	/** Human formula, e.g. '1 - cosine_distance'; 'unknown' when the driver does not say. */
	formula: string;
	range?: [number, number];
	higher_is_better: boolean;
	/** The driver's own floor: search drops rows below it unless asked not to. */
	floor: number;
	/** The node's configured score threshold. */
	threshold: number | null;
}

/** `dialect.health`. */
export interface IVectorHealth {
	collection_exists: boolean;
	/** False means "Repair needed"; null when the collection does not exist. */
	control_record: boolean | null;
	/** True when the node's embedding model differs from the one the collection was built with; null when not checked. */
	model_mismatch: boolean | null;
	/** pgvector: false while the metadata column is pending; null elsewhere. */
	meta_column: boolean | null;
}

/** `dialect` answer. Never carries a host, port, DSN or database name. */
export interface IDialectResult {
	success: true;
	dialect: 'vector';
	/** Contract revision, 'vector/1'. */
	contract: string;
	/** Component provider of the node, e.g. 'postgres', 'qdrant', 'rocketride_vector'. */
	provider: string;
	backend: VectorBackend | string;
	backend_version: string | null;
	collection: string | null;
	metric: VectorMetric | null;
	model: string | null;
	dimension: number | null;
	index: { type: string; params?: Record<string, unknown> } | null;
	score: IScoreInfo;
	support: SupportLevel;
	allow_writes: boolean;
	agent_writes: boolean;
	/** v1: 'tools_source' (external writes are honoured only from a Tools source). */
	writes_scope: string;
	write_tools: string[];
	capabilities: IVectorCapabilities;
	limits: IVectorLimits;
	health: IVectorHealth;
	caveats: Array<Caveat | string>;
}

// -----------------------------------------------------------------------------
// stats
// -----------------------------------------------------------------------------

/** `stats` input. */
export interface IStatsInput {
	/** 'full' (default) recomputes filtered counts; 'quick' returns the raw count plus cached figures. */
	mode?: 'full' | 'quick';
}

/**
 * `stats` answer. `count`, `model` and `vector_size` are the legacy keys (an
 * older node answers only those); the extended keys are null where the store
 * cannot count. A missing collection answers `count: 0, model: '', vector_size: 0,
 * collection_exists: false` with the extended keys null.
 */
export interface IStatsResult {
	success: true;
	/** Legacy semantics (raw rows incl. the control record); shown only in a tooltip. */
	count: number;
	model: string;
	vector_size: number;
	collection_exists?: boolean;
	documents?: number | null;
	documents_without_first_chunk?: number | null;
	chunks?: number | null;
	deleted_chunks?: number | null;
	raw_count?: number | null;
	tables?: number | null;
	avg_chunks_per_document?: number | null;
	dimension?: number | null;
	metric?: VectorMetric | string | null;
	/** UTC ISO-8601 of this answer. */
	computed_at?: string | null;
	/** UTC ISO-8601 of the cached filtered counts. */
	counts_as_of?: string | null;
	caveats?: Array<Caveat | string>;
}

// -----------------------------------------------------------------------------
// documents
// -----------------------------------------------------------------------------

/** `documents` input. */
export interface IDocumentsInput {
	cursor?: string | null;
	/** Clamped to `limits.documents_page` (answer then carries warnings ['limit_clamped']). */
	limit?: number;
	object_ids?: string[] | null;
	deleted?: Deleted;
	sort?: 'path';
}

/** One document (one objectId). */
export interface IDocumentItem {
	objectId: string;
	path: string;
	/** null when the store cannot count chunks per document. */
	chunks: number | null;
	has_first_chunk: boolean;
	tables: number | null;
	deleted: boolean;
	nodeId: string | null;
	size: number | null;
	modifyTime: number | null;
	/** UTC ISO-8601. */
	ingestedAt: string | null;
	pointId: string | null;
}

/** `documents` answer (a list page, never a dict). */
export interface IDocumentsResult {
	success: true;
	items: IDocumentItem[];
	next_cursor: string | null;
	total: number | null;
	counts_exact: boolean;
	distinct: boolean;
	/** false: the client sorts loaded rows (caveat 'documents_unsorted'). */
	sorted: boolean;
	caveats: Array<Caveat | string>;
	warnings?: string[];
}

// -----------------------------------------------------------------------------
// chunks
// -----------------------------------------------------------------------------

/** `chunks` input. `{ object_id, limit: 1 }` is the app's existence probe. */
export interface IChunksInput {
	object_id: string;
	/** Default -1 (from the first chunk). */
	after_chunk?: number;
	limit?: number;
	deleted?: Deleted;
}

/** One chunk. Never carries a vector. */
export interface IChunkItem {
	chunkId: number;
	content: string;
	length: number;
	isTable: boolean;
	tableId: number;
	isDeleted: boolean;
	pointId: string | null;
	metadata: Record<string, unknown>;
}

/** `chunks` answer. NOT_FOUND for 'schema' or an unknown objectId. */
export interface IChunksResult {
	success: true;
	items: IChunkItem[];
	has_more: boolean;
	next_after: number;
	total: number | null;
}

// -----------------------------------------------------------------------------
// vectors (the only tool that returns stored vectors; ≤ 2 keys)
// -----------------------------------------------------------------------------

/** `vectors` input. */
export interface IVectorsInput {
	keys: VectorKey[];
}

/** One stored vector. */
export interface IVectorItem {
	key: VectorKey;
	pointId: string | null;
	dimension: number;
	norm: number;
	values: number[];
}

/** `vectors` answer. */
export interface IVectorsResult {
	success: true;
	items: IVectorItem[];
	model: string | null;
}

// -----------------------------------------------------------------------------
// sample
// -----------------------------------------------------------------------------

/** `sample` input. */
export interface ISampleInput {
	n?: number;
	seed?: number;
	strategy?: SampleStrategy;
	mode?: SampleMode;
	include_keys?: VectorKey[];
	filter?: { object_ids?: string[] | null };
	deleted?: Deleted;
	knn_k?: number;
	components?: 2 | 3;
	duplicate_threshold?: number;
	include_text?: boolean;
}

/** One document represented in a sample. `i` is its index in `docs`. */
export interface ISampleDoc {
	i: number;
	objectId: string;
	path: string;
	chunks: number | null;
	in_sample: number;
}

/** Sample points, columnar (index = point number). */
export interface ISamplePoints {
	/** Index into `docs`. */
	doc: number[];
	chunk: number[];
	/** PCA coordinates. */
	x: number[];
	y: number[];
	z?: number[];
	/** Chunk length in characters. */
	len: number[];
	/** Snippets (≤ snippet_chars); absent in light mode. */
	snip?: string[];
	/** 1 when the point was pinned by `include_keys`. */
	pinned: number[];
}

/** kNN graph in Qdrant's offsets layout: row i's neighbours are cols[offsets_row[i]..offsets_row[i+1]). */
export interface IKnnBlock {
	k: number;
	offsets_row: number[];
	cols: number[];
	sims: number[];
}

/** A near-duplicate pair (point indices). */
export interface IDuplicatePair {
	a: number;
	b: number;
	sim: number;
}

/** `sample` answer. Positions are server-side PCA; no raw vectors. */
export interface ISampleResult {
	success: true;
	/** 's-<seed>-<8 hex>'; cached on the node for `expires_in_s`. */
	sample_id: string;
	expires_in_s: number;
	/** Points actually returned (may be < n_requested). */
	n: number;
	n_requested: number;
	mode: SampleMode;
	of: { chunks: number | null; documents: number | null };
	strategy_used: SampleStrategy;
	/** True when the sample is not uniform (a refill happened, or strategy 'first'). */
	biased: boolean;
	knn_source: KnnSource;
	metric: VectorMetric;
	dimension: number;
	docs: ISampleDoc[];
	points: ISamplePoints;
	knn: IKnnBlock;
	density: number[];
	outliers: number[];
	duplicates: IDuplicatePair[];
	pca: { explained: number[] };
	took_ms: number;
	caveats?: Array<Caveat | string>;
}

// -----------------------------------------------------------------------------
// project
// -----------------------------------------------------------------------------

/** `project` input: exactly one of `vector` (a query vector from `embed`) or `keys`. */
export type IProjectInput =
	| { sample_id: string; vector: number[]; keys?: never; m?: number; with_similarities?: boolean }
	| { sample_id: string; keys: VectorKey[]; vector?: never; m?: number; with_similarities?: boolean };

/** One projected item. */
export interface IProjectItem {
	/** null for a projected vector. */
	key: VectorKey | null;
	/** Point index when the key is in the sample, else null. */
	in_sample: number | null;
	/** Coordinates in the sample's PCA basis. */
	pca: number[];
	/** Nearest sample points. */
	neighbors: Array<{ i: number; sim: number }>;
}

/** `project` answer. SAMPLE_EXPIRED when the node no longer holds the sample. */
export interface IProjectResult {
	success: true;
	items: IProjectItem[];
	/** Similarity of the vector to every sample point (with_similarities). */
	similarities?: number[];
	dimension: number;
}

// -----------------------------------------------------------------------------
// neighbors
// -----------------------------------------------------------------------------

/** `neighbors` input: one of `key` or `vector`. */
export type INeighborsInput = ({ key: VectorKey; vector?: never } | { vector: number[]; key?: never }) & {
	k?: number;
	exclude_self?: boolean;
	filter?: { object_ids?: string[] | null };
	/** Score these keys instead of searching (≤ scope_keys_max). */
	scope_keys?: VectorKey[] | null;
};

/** One neighbour from the whole collection. */
export interface INeighborItem {
	key: VectorKey;
	/** Recomputed by the store's metric (one similarity for every visual). */
	sim: number;
	/** The driver's own score (see dialect.score). */
	score: number | null;
	below_floor: boolean;
	path: string;
	chunkId: number;
	preview: string;
}

/** `neighbors` answer (whole collection). */
export interface INeighborsResult {
	success: true;
	items: INeighborItem[];
	metric: VectorMetric;
	scope: 'collection';
	k_requested: number;
}

/** `neighbors` answer with `scope_keys`. */
export interface INeighborsScopeResult {
	success: true;
	scores: number[];
}

// -----------------------------------------------------------------------------
// search (legacy descriptor; additive DAP extension)
// -----------------------------------------------------------------------------

/** `search` input. `query` alone is the legacy agent call; `vector` is the DAP extension. */
export interface ISearchInput {
	query?: string;
	top_k?: number;
	vector?: number[];
	embedding_model?: string;
	mode?: 'auto' | 'semantic' | 'keyword';
	/** Legacy keys (objectId, nodeId, parent) or the extension keys (objectIds, isTable, minChunkId, maxChunkId). */
	filter?: {
		objectId?: string | string[];
		nodeId?: string;
		parent?: string;
		objectIds?: string[];
		isTable?: boolean;
		minChunkId?: number;
		maxChunkId?: number;
	};
	deleted?: Deleted;
	include_below_floor?: boolean;
	include_below_threshold?: boolean;
}

/** One search result. */
export interface ISearchItem {
	content: string;
	score: number;
	metadata: { objectId?: string; nodeId?: string; parent?: string; chunkId?: number; [key: string]: unknown };
	rank?: number;
	raw_score?: number;
	sim?: number;
	below_threshold?: boolean;
	below_floor?: boolean;
}

/** `search` answer. `warnings` e.g. ['keyword_fallback', '<semantic error>'], ['model_mismatch']. */
export interface ISearchResult {
	success?: true;
	results: ISearchItem[];
	total: number;
	warnings?: string[];
	mode_used?: 'semantic' | 'keyword';
}

// -----------------------------------------------------------------------------
// writes (gated on the node)
// -----------------------------------------------------------------------------

/** The audit block every write answer carries. Never content or vectors. */
export interface IWriteAudit {
	action: string;
	node: string;
	provider: string;
	collection: string | null;
	object_ids: string[];
	rows: number | null;
	caller: { auth: string; userId?: string | null; teamId?: string | null };
}

/** `remove_document` input (1..write_ids_max ids). */
export interface IRemoveDocumentInput {
	object_ids: string[];
}

/** `remove_document` answer. */
export interface IRemoveDocumentResult {
	success: true;
	removed: Array<{ objectId: string; chunks_removed: number | null }>;
	not_found: string[];
	removed_chunks: number | null;
	audit: IWriteAudit;
}

/** `delete` (legacy) input. */
export interface IDeleteInput {
	object_ids: string[];
}

/** `delete` (legacy) answer, extended. */
export interface IDeleteResult {
	success: true;
	deleted_count: number;
	removed_chunks?: number | null;
	not_found?: string[];
	audit?: IWriteAudit;
}

/** `upsert` (legacy) input; the app never calls it. External callers may not supply embeddings. */
export interface IUpsertInput {
	documents: Array<{ content: string; object_id?: string; metadata?: Record<string, unknown> }>;
}

/** `upsert` (legacy) answer. */
export interface IUpsertResult {
	success: boolean;
	[key: string]: unknown;
}

// -----------------------------------------------------------------------------
// get / objdir (legacy descriptors; fixed)
// -----------------------------------------------------------------------------

/** `get` input. */
export interface IGetInput {
	object_id: string;
	offset?: number;
	limit?: number;
}

/** `get` answer. */
export interface IGetResult {
	success: true;
	chunks: Array<{ content: string; chunkId: number; metadata: Record<string, unknown> }>;
	total: number;
	has_more?: boolean;
}

/** `objdir` input. */
export interface IObjdirInput {
	parent?: string;
	offset?: number;
	limit?: number;
}

/** `objdir` answer: legacy `paths` (path -> objectId) plus `entries`. */
export interface IObjdirResult {
	success: true;
	paths: Record<string, string>;
	entries?: Array<{ path: string; objectId: string }>;
}

// -----------------------------------------------------------------------------
// embed (on the embedding node)
// -----------------------------------------------------------------------------

/** `embed` input: 1..8 texts, each ≤ 8,000 characters. */
export interface IEmbedInput {
	texts: string[];
	kind?: 'query' | 'document';
}

/** `embed` answer. RATE_LIMITED carries retry_after_s. */
export interface IEmbedResult {
	success: true;
	model: string;
	dimension: number;
	vectors: number[][];
	prefix_applied: string | null;
	ms: number;
}

// -----------------------------------------------------------------------------
// Typed tool map
// -----------------------------------------------------------------------------

/** Input and answer of every tool, for typed invoke helpers. */
export interface VectorToolMap {
	dialect: { input: Record<string, never>; result: IDialectResult };
	stats: { input: IStatsInput; result: IStatsResult };
	documents: { input: IDocumentsInput; result: IDocumentsResult };
	chunks: { input: IChunksInput; result: IChunksResult };
	vectors: { input: IVectorsInput; result: IVectorsResult };
	sample: { input: ISampleInput; result: ISampleResult };
	project: { input: IProjectInput; result: IProjectResult };
	neighbors: { input: INeighborsInput; result: INeighborsResult | INeighborsScopeResult };
	search: { input: ISearchInput; result: ISearchResult };
	remove_document: { input: IRemoveDocumentInput; result: IRemoveDocumentResult };
	delete: { input: IDeleteInput; result: IDeleteResult };
	upsert: { input: IUpsertInput; result: IUpsertResult };
	get: { input: IGetInput; result: IGetResult };
	objdir: { input: IObjdirInput; result: IObjdirResult };
	embed: { input: IEmbedInput; result: IEmbedResult };
}

// -----------------------------------------------------------------------------
// Chat and upload (data lanes, not tools)
// -----------------------------------------------------------------------------

/** One document in a chat result's `documents` (from the pipeline's response_documents node). */
export interface IChatDocumentWire {
	type?: string;
	page_content: string;
	score?: number;
	metadata: { objectId?: string; chunkId?: number; parent?: string; nodeId?: string; [key: string]: unknown };
}

/** A chat answer as the chat source returns it. */
export interface IChatResultWire {
	answers?: unknown;
	documents?: IChatDocumentWire[];
	result_types?: Record<string, string>;
	[key: string]: unknown;
}

/** A cited source, parsed from a chat answer. */
export interface IChatSource {
	rank: number;
	key: VectorKey;
	objectId: string;
	chunkId: number;
	/** The document path (metadata.parent). */
	path: string;
	/** The driver's score, when present. */
	score: number | null;
	text: string;
}

/** An `apaevt_status_upload` event body (the SDK keys it by file name). */
export interface IUploadEvent {
	action: 'open' | 'write' | 'close' | 'complete' | 'error';
	filepath: string;
	bytes_sent: number;
	file_size: number;
	upload_time: number;
	result?: Record<string, unknown>;
	error?: string;
}

// =============================================================================
// 2. APP TYPES
// =============================================================================

/** A Vector Explorer connection: the shared library's endpoint plus its dialect probe answer. */
export interface VectorEndpoint {
	/** Token-free endpoint (from the shared library). */
	endpoint: IExplorerEndpoint;
	/** The probe's answer; null until it answered or when it failed. */
	dialect: IDialectResult | null;
}

/** Component ids of the nodes a connection uses. */
export interface VectorNodes {
	/** The store node (endpoint.nodeId). */
	store: string;
	/** The embedding node the Tools source reaches (embed_1), or null. */
	embed: string | null;
	/** The LLM node on the chat path, or null. */
	llm: string | null;
	/** The LLM node's display name (the only LLM detail the app shows). */
	llmName: string | null;
}

/** Whether an action is available, and if not, the sentence that says why. */
export interface Availability {
	enabled: boolean;
	/** Shown on the disabled control; null when enabled. */
	reason: string | null;
}

/** The role channels of a connection (shared library `IEndpointStore.channel`); null when the role is not bound. */
export interface VectorChannels {
	tools: IRoleChannel | null;
	chat: IRoleChannel | null;
	ingest: IRoleChannel | null;
}

/**
 * What the console knows about the open connection, handed read-only to every
 * panel and to the map. Rebuilt by the console; panels never mutate it.
 */
export interface ConsoleModel {
	/** endpoint.key — the identity every per-connection cache is keyed by. */
	connectionKey: string;
	connection: VectorEndpoint;
	nodes: VectorNodes;
	/** Collection name (dialect), or null. */
	collection: string | null;
	/** Last `stats` answer, or null before the first. */
	stats: IStatsResult | null;
	/** Limits from the dialect, else the documented defaults. */
	limits: IVectorLimits;
	/** Capabilities from the dialect, else all false. */
	capabilities: IVectorCapabilities;
	/** Remove controls (trash, multi-remove). */
	writes: Availability;
	/** Drop zone / Add files. */
	ingest: Availability;
	/** Chat panel. */
	chat: Availability;
	/** Text queries on the map and "Why these?" (needs `embed` reachable). */
	embed: Availability;
	/** True when the connection is anchored on a Chat or Ingest source (no Tools source running). */
	readOnly: boolean;
}

/** A sample answer as the map holds it (never raw vectors). */
export interface ISampleModel {
	sampleId: string;
	seed: number;
	mode: SampleMode;
	/** Epoch ms when the answer arrived. */
	receivedAt: number;
	result: ISampleResult;
	/** Points added later through `project({ keys })` (answer sources outside the sample). */
	pinned: IProjectItem[];
	/** objectIds removed since the sample was drawn: their points are hidden, indices stay stable. */
	removed: readonly string[];
}

/** Why some keys are highlighted. */
export type HighlightSource = 'chat' | 'search' | 'neighbors' | 'lasso' | 'document';

/** The selection the console, the document tab and the map share (one per connection). */
export interface SelectionState {
	/** The connection this selection belongs to; null after a reset. */
	connectionKey: string | null;
	/** The document selected in the directory. */
	document: { objectId: string; path: string } | null;
	/** The focused chunk (inspector, chunk list). */
	chunk: VectorKey | null;
	/** Multi-selection (lasso, "Selection" tab). */
	keys: readonly VectorKey[];
	/** Highlighted keys and why (answer sources, query top-k, neighbours). */
	highlight: { source: HighlightSource; keys: readonly VectorKey[] } | null;
	/** The last query text run on the map, if any. */
	query: string | null;
	/** The current sample, if one was drawn. */
	sampleModel: ISampleModel | null;
}

/** The shared selection store (see bridge.ts). useSyncExternalStore-compatible. */
export interface SelectionStore {
	getState(): SelectionState;
	subscribe(listener: () => void): () => void;
	/** Forget everything and bind to `connectionKey` (connection change, sign-out with null). */
	reset(connectionKey: string | null): void;
	selectDocument(document: { objectId: string; path: string } | null): void;
	focusChunk(key: VectorKey | null): void;
	setKeys(keys: readonly VectorKey[]): void;
	setHighlight(highlight: SelectionState['highlight']): void;
	setQuery(query: string | null): void;
	setSampleModel(model: ISampleModel | null): void;
	/** Add projected points to the current sample model (no-op without one). */
	addPinned(items: readonly IProjectItem[]): void;
	/** After a removal: drop a document from the selection, highlight and sample model. */
	forgetDocument(objectId: string): void;
}

/** What the map, document tab and panels ask the console to do (they never write on their own). */
export interface ConsoleActions {
	/** Open a document tab, optionally at a chunk. */
	openDocument(objectId: string, chunkId?: number): void;
	/** Switch to the Map tab and highlight these keys. */
	showOnMap(keys: readonly VectorKey[], source: HighlightSource): void;
	/** Ask to remove documents: the console confirms (Cancel focused) and runs the gated write. */
	requestRemove(objectIds: readonly string[]): void;
	/** "Ask about these only": scope the next chat question to these documents. */
	askAbout(objectIds: readonly string[]): void;
	/** After an upload completed or a document changed: refresh stats and the directory. */
	documentsChanged(objectIds: readonly string[]): void;
	/** Announce through the polite live region. */
	announce(message: string): void;
}

// -----------------------------------------------------------------------------
// Props of components rendered across lanes (frozen)
// -----------------------------------------------------------------------------

/** views/MapView.tsx — the second tab of a connection. */
export interface MapViewProps {
	model: ConsoleModel;
	channels: VectorChannels;
	selection: SelectionStore;
	actions: ConsoleActions;
	/** False while the tab is hidden: the canvas must not allocate or animate. */
	visible: boolean;
}

/** views/DocumentView.tsx — a document tab. */
export interface DocumentViewProps {
	model: ConsoleModel;
	channels: VectorChannels;
	selection: SelectionStore;
	actions: ConsoleActions;
	objectId: string;
	/** Known path, or null until loaded. */
	path: string | null;
	/** Chunk to scroll to on open. */
	chunkId?: number;
}

/** components/ChatPanel.tsx — the console's chat (R5). */
export interface ChatPanelProps {
	model: ConsoleModel;
	channels: VectorChannels;
	selection: SelectionStore;
	actions: ConsoleActions;
	/** objectIds the next question is restricted to ("Ask about these only"), or null. */
	scope: readonly string[] | null;
	/** Clear the scope. */
	onClearScope(): void;
}

/** components/IngestPanel.tsx — the console's drop zone and upload list (R4). */
export interface IngestPanelProps {
	model: ConsoleModel;
	channels: VectorChannels;
	actions: ConsoleActions;
	/** Names of other store nodes the ingest source also feeds ("This pipeline's ingest also reaches: …"). */
	alsoReaches: readonly string[];
}

/** components/HeatStrip.tsx — per-chunk similarity strip of one document for the active query. */
export interface HeatStripProps {
	/** Number of chunks in the document. */
	chunks: number;
	/** Similarity per chunk id that has one. */
	scores: ReadonlyArray<{ chunkId: number; sim: number }>;
	/** The chunk to outline, if any. */
	focused: number | null;
	onSelectChunk(chunkId: number): void;
	/** Accessible name, e.g. 'Similarity of each chunk to the query'. */
	label: string;
}

// -----------------------------------------------------------------------------
// Props of lane-internal components (the owning lane may add optional fields)
// -----------------------------------------------------------------------------

/** components/SourcesPanel.tsx (inside ChatPanel). */
export interface SourcesPanelProps {
	sources: readonly IChatSource[];
	score: IScoreInfo | null;
	onOpen(source: IChatSource): void;
	onShowOnMap(keys: readonly VectorKey[]): void;
}

/** components/RetrievalDebugger.tsx ("Why these?", inside ChatPanel). */
export interface RetrievalDebuggerProps {
	model: ConsoleModel;
	channels: VectorChannels;
	question: string;
	/** The answer's top-k (the debugger asks for k + 10). */
	topK: number;
	onClose(): void;
}

/** Layouts the map offers. */
export type MapLayout = 'pca' | 'neighbour-graph' | 'tsne';

/** Colour modes of the map. */
export type ColourBy = 'document' | 'folder' | 'type' | 'chunk-position' | 'query-similarity' | 'density';

/** components/MapToolbar.tsx (inside MapView). */
export interface MapToolbarProps {
	limits: IVectorLimits;
	sample: ISampleModel | null;
	/** Busy label, e.g. 'Sampling…', 'Laying out…', or null. */
	busy: string | null;
	layout: MapLayout;
	colourBy: ColourBy;
	lasso: boolean;
	table: boolean;
	query: Availability;
	onSample(options: { n: number; mode: SampleMode; seed: number }): void;
	onLayout(layout: MapLayout): void;
	onCancel(): void;
	onColourBy(colourBy: ColourBy): void;
	onQuery(text: string): void;
	onToggleLasso(): void;
	onFit(): void;
	onToggleTable(): void;
}

/** components/PointCanvas.tsx (inside MapView). Positions are 2D or 3D layout coordinates, never vectors. */
export interface PointCanvasProps {
	sample: ISampleModel;
	/** Interleaved x,y(,z) per point from the current layout. */
	positions: Float32Array;
	dimensions: 2 | 3;
	/** One CSS colour per point. */
	colours: readonly string[];
	selection: SelectionStore;
	lasso: boolean;
	onHover(index: number | null): void;
	onPick(index: number | null): void;
	onLasso(indices: readonly number[]): void;
}

/** components/PointInspector.tsx (inside MapView). */
export interface PointInspectorProps {
	sample: ISampleModel;
	/** Point index, or null. */
	index: number | null;
	neighbours: INeighborsResult | null;
	/** Similarity to the active query, when there is one. */
	querySim: number | null;
	writes: Availability;
	onOpenDocument(objectId: string, chunkId: number): void;
	onFindSimilar(key: VectorKey): void;
	onRemoveDocument(objectId: string): void;
}

/** components/NeighbourList.tsx (inside PointInspector). */
export interface NeighbourListProps {
	items: readonly INeighborItem[];
	onSelect(key: VectorKey): void;
}

/** components/DuplicatesPanel.tsx (inside MapView). */
export interface DuplicatesPanelProps {
	sample: ISampleModel;
	writes: Availability;
	onSelect(indices: readonly number[]): void;
	onRemoveDocument(objectId: string): void;
}

/** components/OutliersPanel.tsx (inside MapView). */
export interface OutliersPanelProps {
	sample: ISampleModel;
	onSelect(index: number): void;
}

/** components/PointsTable.tsx (the accessible alternative to the canvas). */
export interface PointsTableProps {
	sample: ISampleModel;
	/** Similarity to the active query per point, when there is one. */
	querySims: readonly number[] | null;
	selected: number | null;
	onSelect(index: number): void;
}

/** components/Legend.tsx (inside MapView). */
export interface LegendProps {
	sample: ISampleModel;
	colourBy: ColourBy;
	/** Point cap of the current mode (2,000 detailed / 5,000 light). */
	pointCap: number;
	/** Backend name for "neighbour graph computed by <backend>" when knn_source is 'native'. */
	backend: string | null;
}
