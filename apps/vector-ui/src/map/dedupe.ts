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
// MAP - NEAR-DUPLICATE GROUPS (pure; frozen signatures, not built yet)
// =============================================================================
//
// The duplicates queue groups near-duplicate pairs into connected groups and
// numbers every point by its group, from what the sample already holds: the
// node's `sample.duplicates` and every kNN pair of `sample.knn` at or above the
// threshold, so moving the threshold re-groups without a call. The Points
// table's Notes column and the Duplicates tab both read these functions.
//
// The signatures below are frozen; until the queue is built they answer
// "no pairs, no groups", which every caller already handles.
// =============================================================================

import type { IDuplicatePair, ISampleResult } from '../contract/types';

/** A connected group of near-duplicate points, numbered by size (largest first). */
export interface IDuplicateGroup {
	/** The group's number. */
	id: number;
	/** Point indices, ascending. */
	points: readonly number[];
	/** The lowest and highest similarity of the pairs inside the group. */
	simMin: number;
	simMax: number;
}

/**
 * The near-duplicate pairs of a sample at a threshold: `sample.duplicates` plus
 * every kNN pair at or above it, each pair once (a < b).
 *
 * @param _sample - The `sample` answer.
 * @param _threshold - The similarity a pair needs (0.90 to 0.995 in the queue).
 * @returns The pairs (none until the queue is built).
 */
export function pairsAt(_sample: ISampleResult, _threshold: number): IDuplicatePair[] {
	return [];
}

/**
 * The connected groups of pairs (union-find over the pairs).
 *
 * @param _pairs - The pairs.
 * @returns The groups (none until the queue is built).
 */
export function groups(_pairs: readonly IDuplicatePair[]): IDuplicateGroup[] {
	return [];
}

/**
 * Every point's group number, or -1 when it is in none.
 *
 * @param found - The groups.
 * @param n - The sample's point count.
 * @returns One group number per point.
 */
export function groupOf(found: readonly IDuplicateGroup[], n: number): Int32Array {
	const out = new Int32Array(Math.max(0, n)).fill(-1);
	for (const group of found) for (const i of group.points) if (i >= 0 && i < out.length) out[i] = group.id;
	return out;
}
