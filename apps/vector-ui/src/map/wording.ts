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
// MAP - WORDING (every sentence the map shows, in one place)
// =============================================================================
//
// Plain, specific sentences in the style of SQL and Graph Explorer: what
// happened, what is not known, and what to do next. Numbers go through
// toLocaleString('en-US'). Never claim a count the node did not return.
// =============================================================================

import type { ISampleResult, SampleMode } from '../contract/types';

/** en-US number. */
export function num(value: number): string {
	return value.toLocaleString('en-US');
}

/**
 * The sample line: how many points of how many chunks, and whether the sample is uniform.
 *
 * @param sample - The answer.
 * @returns E.g. "Showing 1,000 of 1,318 chunks (random sample)".
 */
export function sampleLabel(sample: ISampleResult): string {
	const uniform = sample.strategy_used !== 'first' && !sample.biased;
	const of = sample.of.chunks;
	let text: string;
	if (of === null || of === undefined) text = `Showing ${num(sample.n)} chunks (${uniform ? 'random sample' : 'not a uniform sample'}; the store did not say how many it holds)`;
	else text = `Showing ${num(sample.n)} of ${num(of)} chunks (${uniform ? 'random sample' : 'not a uniform sample'})`;
	if (sample.n < sample.n_requested) text += `; fewer points than requested: the store returned ${num(sample.n)}`;
	return text;
}

/**
 * Why a sample is not uniform, when it is not.
 *
 * @param sample - The answer.
 * @returns A sentence, or null for a uniform sample.
 */
export function biasedNote(sample: ISampleResult): string | null {
	if (sample.biased) return 'Some documents could not be sampled evenly, so the store filled the sample with other chunks.';
	if (sample.strategy_used === 'first') return 'This store returned its first chunks rather than a random sample.';
	return null;
}

/** The legend's caveat on what the picture means. */
export const DISTANCE_CAVEAT = '2D distance is approximate; ranks and scores are exact';

/** Display names of backends, for "neighbour graph computed by <backend>". */
const BACKEND_NAMES: Record<string, string> = { qdrant: 'Qdrant', pgvector: 'pgvector', chroma: 'Chroma', milvus: 'Milvus', weaviate: 'Weaviate', pinecone: 'Pinecone', astra: 'Astra DB', atlas: 'MongoDB Atlas' };

/**
 * The display name of a backend.
 *
 * @param backend - `dialect.backend`.
 * @returns A name.
 */
export function backendName(backend: string | null | undefined): string {
	if (!backend) return 'the store';
	return BACKEND_NAMES[backend] ?? backend;
}

/**
 * Who computed the neighbour graph.
 *
 * @param sample - The answer.
 * @param backend - `dialect.backend`.
 * @returns The legend line.
 */
export function knnSourceLine(sample: ISampleResult, backend: string | null): string {
	return sample.knn_source === 'native' ? `neighbour graph computed by ${backendName(backend)}` : 'neighbour graph computed by the store node';
}

/**
 * The point cap line of the legend.
 *
 * @param mode - The sample mode.
 * @param cap - The cap of that mode.
 * @returns E.g. "Detailed mode draws up to 2,000 points".
 */
export function pointCapLine(mode: SampleMode, cap: number): string {
	return `${mode === 'light' ? 'Light' : 'Detailed'} mode draws up to ${num(cap)} points`;
}

/** Shown instead of the map when the store cannot sample. */
export const MAP_UNAVAILABLE = 'This store cannot draw a sample of its points, so there is no map for it. The Console lists every document.';

/** The refined layout was no better than PCA. */
export const LAYOUT_NOT_BETTER = 'Neighbour layout did not improve on PCA for this sample';

/** Text queries cannot run. */
export const QUERY_NEEDS_EMBED = 'Text queries need the embedding node reachable from the Tools source';

/** A query was run before any sample was drawn (or after sampling failed). */
export const QUERY_NEEDS_SAMPLE = 'Draw a sample of the collection first; the query is placed among its points.';

/** On a refined layout the query cannot be projected exactly. */
export const QUERY_PLACED_APPROX = 'On this layout the query is placed among its nearest points (approximate); its rays go to the true top results.';

/** The chat star without a query vector. */
export const CENTROID_APPROX = 'approximate: the centre of the answer\'s sources';

/** Cancelled layout. */
export const LAYOUT_CANCELLED = 'Layout cancelled. The map shows PCA.';

/** Busy labels. */
export const BUSY = { sampling: 'Sampling…', layout: 'Laying out…', embedding: 'Embedding…', projecting: 'Placing the query…', neighbours: 'Finding neighbours…' } as const;

/**
 * The sentence for a failed map call.
 *
 * @param code - The failure code, if any.
 * @param fallback - The node's own error text.
 * @returns A sentence.
 */
export function mapFailure(code: string | undefined, fallback: string): string {
	switch (code) {
		case 'BUSY':
			return 'The store is computing another sample or neighbour search; try again in a moment.';
		case 'TIMEOUT':
			return 'The store did not finish within its time budget. Draw a smaller sample or use light mode.';
		case 'LIMIT_EXCEEDED':
			return 'That request is larger than this store allows; choose fewer points or light mode.';
		case 'UNSUPPORTED':
			return 'This store cannot do that.';
		case 'COLLECTION_MISSING':
			return 'The collection does not exist yet. Add a document in the Console first.';
		case 'SAMPLE_EXPIRED':
			return 'The store no longer holds this sample; it was drawn again.';
		case 'DIMENSION_MISMATCH':
			return 'The query vector does not match this collection\'s dimension: the embedding node uses another model.';
		case 'NOT_FOUND':
			return 'That chunk is no longer in the store.';
		case 'RATE_LIMITED':
			return 'The embedding node is limiting requests; wait a few seconds and run the query again.';
		case 'NO_EMBEDDER':
			return QUERY_NEEDS_EMBED;
		default:
			return fallback ? `The store refused this request: ${fallback}` : 'The store refused this request; see the pipeline\'s run log.';
	}
}

/**
 * The announcement for a keyboard move.
 *
 * @param index - Point index.
 * @param total - Visible points.
 * @param path - Document path.
 * @param chunk - Chunk id.
 * @returns E.g. "Point 12 of 1,000: C:/demo/a.md, chunk 3".
 */
export function pointAnnouncement(index: number, total: number, path: string, chunk: number): string {
	return `Point ${num(index + 1)} of ${num(total)}: ${path}, chunk ${num(chunk)}`;
}
