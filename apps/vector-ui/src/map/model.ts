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
// MAP - SAMPLE MODEL HELPERS (pure; no vectors anywhere)
// =============================================================================
//
// The `sample` answer is columnar: point i is (docs[doc[i]], chunk[i]) at
// (x[i], y[i], z[i]). These helpers give the map keys, the hidden mask of
// removed documents (indices never shift: a removed document's points are only
// hidden), PCA positions, a document's chunk path and a point's neighbours from
// the node's kNN graph.
// =============================================================================

import type { ISampleDoc, ISampleModel, ISampleResult, VectorKey } from '../contract/types';

/**
 * The string form of a key.
 *
 * @param objectId - Document.
 * @param chunkId - Chunk.
 * @returns `objectId#chunkId`.
 */
export function keyString(objectId: string, chunkId: number): string {
	return `${objectId}#${chunkId}`;
}

/**
 * The key of a point.
 *
 * @param sample - The answer.
 * @param i - Point index.
 * @returns (objectId, chunkId).
 */
export function pointKey(sample: ISampleResult, i: number): VectorKey {
	return [sample.docs[sample.points.doc[i] as number]?.objectId ?? '', sample.points.chunk[i] as number];
}

/**
 * The document of a point.
 *
 * @param sample - The answer.
 * @param i - Point index.
 * @returns Its docs row.
 */
export function documentOf(sample: ISampleResult, i: number): ISampleDoc | null {
	return sample.docs[sample.points.doc[i] as number] ?? null;
}

/**
 * Point index by key string.
 *
 * @param sample - The answer.
 * @returns `objectId#chunkId` to index.
 */
export function keyIndex(sample: ISampleResult): Map<string, number> {
	const out = new Map<string, number>();
	for (let i = 0; i < sample.n; i += 1) {
		const [objectId, chunk] = pointKey(sample, i);
		const key = keyString(objectId, chunk);
		if (!out.has(key)) out.set(key, i);
	}
	return out;
}

/**
 * The mask of points whose document was removed since the sample was drawn.
 *
 * @param model - The sample model.
 * @returns 1 per hidden point, or null when nothing is hidden.
 */
export function hiddenMask(model: ISampleModel): Uint8Array | null {
	if (model.removed.length === 0) return null;
	const removed = new Set(model.removed);
	const docs = model.result.docs.map((d) => removed.has(d.objectId));
	if (!docs.some(Boolean)) return null;
	const mask = new Uint8Array(model.result.n);
	for (let i = 0; i < model.result.n; i += 1) mask[i] = docs[model.result.points.doc[i] as number] ? 1 : 0;
	return mask;
}

/**
 * Points still drawn.
 *
 * @param model - The sample model.
 * @returns The count.
 */
export function visibleCount(model: ISampleModel): number {
	const mask = hiddenMask(model);
	if (mask === null) return model.result.n;
	let hidden = 0;
	for (const v of mask) hidden += v;
	return model.result.n - hidden;
}

/**
 * The node's PCA coordinates.
 *
 * @param sample - The answer.
 * @param dims - 2 or 3 (z is 0 when the answer has none).
 * @returns Coordinates, `dims` per point.
 */
export function pcaPositions(sample: ISampleResult, dims: 2 | 3): Float32Array {
	const out = new Float32Array(sample.n * dims);
	const z = sample.points.z;
	for (let i = 0; i < sample.n; i += 1) {
		out[i * dims] = sample.points.x[i] ?? 0;
		out[i * dims + 1] = sample.points.y[i] ?? 0;
		if (dims === 3) out[i * dims + 2] = z ? (z[i] ?? 0) : 0;
	}
	return out;
}

/**
 * A document's sampled points in chunk order (the "chunk path").
 *
 * @param sample - The answer.
 * @param objectId - The document.
 * @returns Point indices.
 */
export function chunkPath(sample: ISampleResult, objectId: string): number[] {
	const doc = sample.docs.findIndex((d) => d.objectId === objectId);
	if (doc < 0) return [];
	const out: number[] = [];
	for (let i = 0; i < sample.n; i += 1) if (sample.points.doc[i] === doc) out.push(i);
	return out.sort((a, b) => (sample.points.chunk[a] as number) - (sample.points.chunk[b] as number) || a - b);
}

/**
 * A point's neighbours in the node's kNN graph (sample points only).
 *
 * @param sample - The answer.
 * @param i - Point index.
 * @param limit - Most to return.
 * @returns Neighbours, nearest first, with the node's similarity.
 */
export function neighboursOf(sample: ISampleResult, i: number, limit = Infinity): Array<{ i: number; sim: number }> {
	const start = sample.knn.offsets_row[i] ?? 0;
	const end = sample.knn.offsets_row[i + 1] ?? start;
	const out: Array<{ i: number; sim: number }> = [];
	for (let e = start; e < end && out.length < limit; e += 1) out.push({ i: sample.knn.cols[e] as number, sim: sample.knn.sims[e] as number });
	return out;
}
