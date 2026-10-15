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
// MAP - NEAR-DUPLICATE GROUPS AND THE DUPLICATES QUEUE (pure)
// =============================================================================
//
// The duplicates queue is computed in the browser from what the sample
// already holds: the node's `sample.duplicates` and every kNN pair of
// `sample.knn` at or above the threshold, so moving the threshold re-groups
// at once and sends nothing to the store. Pairs are joined into point groups
// by union-find; the queue then shows one group per SET OF DOCUMENTS (a
// copied file pairs up chunk by chunk, and those point groups are one
// decision), and lists a group whose points all sit in one document apart
// ("repeated text inside one document"), never offering to remove it.
//
// A keep policy (oldest ingest, shortest path, most chunks) or a hand-picked
// keep chooses one document per group; the others are queued for removal,
// except a document another group keeps. Removal itself is the console's:
// the panel hands the queued objectIds to `requestRemove`, which confirms
// with the typed count and sends `remove_document` in batches.
//
// The reviewed documents of a connection live in the registry's 'reviewed
// documents' cache (adapters/connections.ts), cleared on a change of
// identity; the helpers below take that map so they stay pure.
//
// `pairsAt`, `groups` and `groupOf` keep the signatures frozen on day 0 (the
// Points table numbers its rows through them).
// =============================================================================

import type { IDocumentItem, IDuplicatePair, ISampleResult } from '../contract/types';

// =============================================================================
// CONSTANTS
// =============================================================================

/** Lowest similarity the queue's slider offers. */
export const THRESHOLD_MIN = 0.9;

/** Highest similarity the queue's slider offers. */
export const THRESHOLD_MAX = 0.995;

/** The slider's step. */
export const THRESHOLD_STEP = 0.005;

/** The queue's starting threshold (the node's own duplicate threshold). */
export const THRESHOLD_DEFAULT = 0.97;

/** Most groups the panel draws (the largest first). */
export const GROUPS_SHOWN_MAX = 200;

/** Most pairs listed under one group. */
export const PAIRS_SHOWN_MAX = 10;

/** How a group's kept document is chosen. */
export type KeepPolicy = 'oldest' | 'shortest-path' | 'most-chunks' | 'manual';

/** The policies, in the picker's order. */
export const KEEP_POLICIES: readonly KeepPolicy[] = ['oldest', 'shortest-path', 'most-chunks', 'manual'];

// =============================================================================
// PAIRS AND POINT GROUPS (frozen signatures)
// =============================================================================

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
 * The near-duplicate pairs of a sample at a threshold: the node's
 * `sample.duplicates` and every kNN edge at or above it, each pair once
 * (a < b) with its highest similarity, most similar first, then by index.
 *
 * @param sample - The `sample` answer.
 * @param threshold - The similarity a pair needs (0.90 to 0.995 in the queue).
 * @returns The pairs.
 */
export function pairsAt(sample: ISampleResult, threshold: number): IDuplicatePair[] {
	const best = new Map<number, IDuplicatePair>();
	const n = sample.n;
	const add = (i: number, j: number, sim: number): void => {
		if (i === j || !(sim >= threshold) || i < 0 || j < 0 || i >= n || j >= n) return;
		const a = Math.min(i, j);
		const b = Math.max(i, j);
		const id = a * n + b;
		const known = best.get(id);
		if (known === undefined || sim > known.sim) best.set(id, { a, b, sim });
	};
	for (const pair of sample.duplicates) add(pair.a, pair.b, pair.sim);
	const { offsets_row: offsets, cols, sims } = sample.knn;
	for (let i = 0; i < offsets.length - 1 && i < n; i += 1) {
		const end = offsets[i + 1] as number;
		for (let e = offsets[i] as number; e < end; e += 1) add(i, cols[e] as number, sims[e] as number);
	}
	return [...best.values()].sort((x, y) => y.sim - x.sim || x.a - y.a || x.b - y.b);
}

/**
 * Find a point's root, halving the path on the way (union-find).
 *
 * @param parent - The parent array.
 * @param i - A point.
 * @returns Its root.
 */
function find(parent: Map<number, number>, i: number): number {
	let x = i;
	for (;;) {
		const p = parent.get(x) ?? x;
		if (p === x) return x;
		const grand = parent.get(p) ?? p;
		parent.set(x, grand);
		x = grand;
	}
}

/**
 * The connected groups of pairs (union-find over the pairs, path halving):
 * numbered by size, largest first, ties by their first point.
 *
 * @param pairs - The pairs.
 * @returns The groups.
 */
export function groups(pairs: readonly IDuplicatePair[]): IDuplicateGroup[] {
	const parent = new Map<number, number>();
	for (const { a, b } of pairs) {
		if (!parent.has(a)) parent.set(a, a);
		if (!parent.has(b)) parent.set(b, b);
		const ra = find(parent, a);
		const rb = find(parent, b);
		if (ra !== rb) parent.set(Math.max(ra, rb), Math.min(ra, rb));
	}
	const members = new Map<number, number[]>();
	for (const point of parent.keys()) {
		const root = find(parent, point);
		const list = members.get(root);
		if (list) list.push(point);
		else members.set(root, [point]);
	}
	const range = new Map<number, { min: number; max: number }>();
	for (const { a, sim } of pairs) {
		const root = find(parent, a);
		const r = range.get(root);
		if (r) {
			r.min = Math.min(r.min, sim);
			r.max = Math.max(r.max, sim);
		} else range.set(root, { min: sim, max: sim });
	}
	const found = [...members.entries()].map(([root, points]) => ({ root, points: points.sort((x, y) => x - y) }));
	found.sort((x, y) => y.points.length - x.points.length || (x.points[0] as number) - (y.points[0] as number));
	return found.map((g, id) => ({ id, points: g.points, simMin: range.get(g.root)?.min ?? 1, simMax: range.get(g.root)?.max ?? 1 }));
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

// =============================================================================
// QUEUE GROUPS (one per set of documents)
// =============================================================================

/** A queue group: the point groups over one set of documents. */
export interface IDocumentGroup extends IDuplicateGroup {
	/** The documents' objectIds joined (stable across thresholds; the keep choices are stored under it). */
	key: string;
	/** The documents, by objectId. */
	objectIds: readonly string[];
	/** True when every point is in one document (repeated text; never removed from here). */
	sameDocument: boolean;
	/** How many point groups were merged into this one. */
	chunkGroups: number;
	/** Points of each document inside the group. */
	shared: Readonly<Record<string, number>>;
	/** The pairs inside the group, most similar first. */
	pairs: readonly IDuplicatePair[];
}

/** What the duplicates queue shows at one threshold. */
export interface IDedupeView {
	threshold: number;
	/** Every pair at the threshold between documents still stored. */
	pairs: IDuplicatePair[];
	/** Groups across documents, numbered from 0 (most documents first, then most points). */
	groups: IDocumentGroup[];
	/** Groups inside one document, numbered after `groups`. */
	repeated: IDocumentGroup[];
}

/**
 * The duplicates queue's groups at a threshold. Pairs touching a removed
 * document are dropped first, so a removal shrinks or resolves its groups.
 *
 * @param sample - The `sample` answer.
 * @param threshold - The similarity a pair needs.
 * @param removed - objectIds removed since the sample was drawn.
 * @returns The pairs, the groups across documents and the groups inside one.
 */
export function dedupeView(sample: ISampleResult, threshold: number, removed: readonly string[] = []): IDedupeView {
	const gone = new Set(removed);
	const objectOf = (i: number): string => sample.docs[sample.points.doc[i] as number]?.objectId ?? '';
	const pairs = pairsAt(sample, threshold).filter((p) => !gone.has(objectOf(p.a)) && !gone.has(objectOf(p.b)));
	const pointGroups = groups(pairs);
	const groupOfPoint = groupOf(pointGroups, sample.n);
	const merged = new Map<string, { objectIds: string[]; points: number[]; chunkGroups: number; simMin: number; simMax: number; pairs: IDuplicatePair[] }>();
	const keyOfGroup: string[] = [];
	for (const group of pointGroups) {
		const objectIds = [...new Set(group.points.map(objectOf))].sort();
		const key = objectIds.join('\n');
		keyOfGroup[group.id] = key;
		const into = merged.get(key);
		if (into) {
			into.points.push(...group.points);
			into.chunkGroups += 1;
			into.simMin = Math.min(into.simMin, group.simMin);
			into.simMax = Math.max(into.simMax, group.simMax);
		} else merged.set(key, { objectIds, points: [...group.points], chunkGroups: 1, simMin: group.simMin, simMax: group.simMax, pairs: [] });
	}
	for (const pair of pairs) merged.get(keyOfGroup[groupOfPoint[pair.a] as number] as string)?.pairs.push(pair);
	const all = [...merged.entries()].map(([key, g]) => {
		const points = g.points.sort((x, y) => x - y);
		const shared: Record<string, number> = {};
		for (const i of points) shared[objectOf(i)] = (shared[objectOf(i)] ?? 0) + 1;
		return { key, objectIds: g.objectIds, points, chunkGroups: g.chunkGroups, simMin: g.simMin, simMax: g.simMax, pairs: g.pairs, shared, sameDocument: g.objectIds.length === 1 };
	});
	const order = (x: (typeof all)[number], y: (typeof all)[number]): number => y.objectIds.length - x.objectIds.length || y.points.length - x.points.length || (x.points[0] as number) - (y.points[0] as number);
	const across = all.filter((g) => !g.sameDocument).sort(order);
	const inside = all.filter((g) => g.sameDocument).sort(order);
	return {
		threshold,
		pairs,
		groups: across.map((g, id) => ({ ...g, id })),
		repeated: inside.map((g, i) => ({ ...g, id: across.length + i })),
	};
}

/**
 * Every point's queue group number (the Points table's notes), or -1.
 *
 * @param sample - The `sample` answer.
 * @param threshold - The queue's threshold.
 * @param removed - objectIds removed since the sample was drawn.
 * @returns One group number per point.
 */
export function duplicateGroupOf(sample: ISampleResult, threshold: number = THRESHOLD_DEFAULT, removed: readonly string[] = []): Int32Array {
	const view = dedupeView(sample, threshold, removed);
	return groupOf([...view.groups, ...view.repeated], sample.n);
}

// =============================================================================
// DOCUMENTS AND KEEP POLICIES
// =============================================================================

/** What the queue knows about a document. */
export interface IDocInfo {
	objectId: string;
	path: string;
	/** Chunks the store reported for it, or null. */
	chunks: number | null;
	/** UTC ISO-8601, or null when the store does not keep it or the row is not loaded. */
	ingestedAt: string | null;
	/** Bytes, or null. */
	size: number | null;
	/** Its points in the sample. */
	inSample: number;
}

/**
 * The documents of a sample, joined with the console's loaded directory rows
 * (a row's path, chunk count, ingest time and size win; the sample fills in).
 *
 * @param sample - The `sample` answer.
 * @param rows - The directory rows loaded so far, or null.
 * @returns The documents by objectId.
 */
export function docInfo(sample: ISampleResult, rows: readonly IDocumentItem[] | null | undefined): Map<string, IDocInfo> {
	const byId = new Map<string, IDocumentItem>();
	for (const r of rows ?? []) byId.set(r.objectId, r);
	const out = new Map<string, IDocInfo>();
	for (const doc of sample.docs) {
		const r = byId.get(doc.objectId);
		out.set(doc.objectId, { objectId: doc.objectId, path: r?.path || doc.path, chunks: r?.chunks ?? doc.chunks, ingestedAt: r?.ingestedAt ?? null, size: r?.size ?? null, inSample: doc.in_sample });
	}
	return out;
}

/**
 * The value a policy ranks documents by, smaller first; null when unknown.
 *
 * @param doc - The document.
 * @param policy - The policy.
 * @returns The rank value.
 */
function rankValue(doc: IDocInfo | undefined, policy: KeepPolicy): number | null {
	if (!doc) return null;
	if (policy === 'oldest') {
		const t = doc.ingestedAt ? Date.parse(doc.ingestedAt) : NaN;
		return Number.isFinite(t) ? t : null;
	}
	if (policy === 'shortest-path') return doc.path ? doc.path.length : null;
	if (policy === 'most-chunks') return doc.chunks === null ? null : -doc.chunks;
	return null;
}

/**
 * The document a policy keeps in a group: the oldest ingest, the shortest
 * path or the most chunks; ties by objectId, unknown values last. Null when
 * the policy is "choose manually" or no document of the group has the value.
 *
 * @param group - The group's documents.
 * @param policy - The policy.
 * @param info - The documents (docInfo).
 * @returns The kept objectId, or null.
 */
export function applyPolicy(group: Pick<IDocumentGroup, 'objectIds'>, policy: KeepPolicy, info: ReadonlyMap<string, IDocInfo>): string | null {
	if (policy === 'manual') return null;
	let kept: string | null = null;
	let keptValue = Infinity;
	for (const objectId of [...group.objectIds].sort()) {
		const value = rankValue(info.get(objectId), policy);
		if (value !== null && value < keptValue) {
			kept = objectId;
			keptValue = value;
		}
	}
	return kept;
}

/**
 * Whether a policy can choose in any group: the ingest time or the chunk
 * count of at least one document is known.
 *
 * @param found - The groups.
 * @param policy - The policy.
 * @param info - The documents.
 * @returns True when the policy picks somewhere.
 */
export function policyChooses(found: readonly IDocumentGroup[], policy: KeepPolicy, info: ReadonlyMap<string, IDocInfo>): boolean {
	if (policy === 'manual') return true;
	return found.some((g) => applyPolicy(g, policy, info) !== null);
}

// =============================================================================
// THE QUEUE (a reducer; nothing here reaches the store)
// =============================================================================

/** The queue's choices. */
export interface IQueueState {
	threshold: number;
	policy: KeepPolicy;
	/** Hand-picked keeps by group key. */
	overrides: Readonly<Record<string, string>>;
}

/** What the queue's controls do. */
export type QueueAction = { type: 'threshold'; value: number } | { type: 'policy'; value: KeepPolicy } | { type: 'keep'; group: string; objectId: string };

/**
 * The queue's starting choices: the node's threshold, nothing kept yet.
 *
 * @returns The state.
 */
export function queueInit(): IQueueState {
	return { threshold: THRESHOLD_DEFAULT, policy: 'manual', overrides: {} };
}

/**
 * Clamp a threshold to the slider's range, on its step.
 *
 * @param value - Any number.
 * @returns The threshold.
 */
export function clampThreshold(value: number): number {
	if (!Number.isFinite(value)) return THRESHOLD_DEFAULT;
	const stepped = Math.round(value / THRESHOLD_STEP) * THRESHOLD_STEP;
	return Math.min(THRESHOLD_MAX, Math.max(THRESHOLD_MIN, Number(stepped.toFixed(3))));
}

/**
 * Apply one control.
 *
 * @param state - The choices.
 * @param action - What changed.
 * @returns The new choices (a new policy replaces the hand-picked keeps).
 */
export function queueReducer(state: IQueueState, action: QueueAction): IQueueState {
	switch (action.type) {
		case 'threshold':
			return { ...state, threshold: clampThreshold(action.value) };
		case 'policy':
			return { ...state, policy: action.value, overrides: {} };
		case 'keep':
			return { ...state, overrides: { ...state.overrides, [action.group]: action.objectId } };
		default:
			return state;
	}
}

/**
 * The document a group keeps: the hand-picked one, else the policy's.
 *
 * @param group - The group.
 * @param state - The choices.
 * @param info - The documents.
 * @returns The kept objectId, or null when none is chosen.
 */
export function keepOf(group: IDocumentGroup, state: IQueueState, info: ReadonlyMap<string, IDocInfo>): string | null {
	const picked = state.overrides[group.key];
	if (picked !== undefined && group.objectIds.includes(picked)) return picked;
	return applyPolicy(group, state.policy, info);
}

/**
 * Whether every document of a group was marked reviewed.
 *
 * @param group - The group.
 * @param reviewed - The connection's reviewed documents.
 * @returns True when the group is out of the queue.
 */
export function isReviewed(group: Pick<IDocumentGroup, 'objectIds'>, reviewed: ReadonlySet<string>): boolean {
	return group.objectIds.length > 0 && group.objectIds.every((id) => reviewed.has(id));
}

/** The queue's content. */
export interface IQueued {
	/** Documents to remove, in group order, each once. */
	objectIds: string[];
	/** The documents each group queues, by group key. */
	byGroup: Map<string, string[]>;
	/** Documents a group would queue but another group keeps (not queued). */
	conflicts: string[];
}

/**
 * The documents queued for removal: for every group across documents that is
 * not reviewed and has a kept document, the others; a document any group
 * keeps is never queued, and a group inside one document never queues.
 *
 * @param found - The groups.
 * @param state - The choices.
 * @param info - The documents.
 * @param reviewed - The connection's reviewed documents.
 * @returns The queue.
 */
export function queued(found: readonly IDocumentGroup[], state: IQueueState, info: ReadonlyMap<string, IDocInfo>, reviewed: ReadonlySet<string>): IQueued {
	const open = found.filter((g) => !g.sameDocument && !isReviewed(g, reviewed));
	const kept = new Set<string>();
	const keeps = new Map<string, string>();
	for (const g of open) {
		const keep = keepOf(g, state, info);
		if (keep !== null) {
			kept.add(keep);
			keeps.set(g.key, keep);
		}
	}
	const objectIds: string[] = [];
	const seen = new Set<string>();
	const conflicts = new Set<string>();
	const byGroup = new Map<string, string[]>();
	for (const g of open) {
		const keep = keeps.get(g.key);
		if (keep === undefined) continue;
		const others = g.objectIds.filter((id) => id !== keep);
		const mine: string[] = [];
		for (const id of others) {
			if (kept.has(id)) {
				conflicts.add(id);
				continue;
			}
			mine.push(id);
			if (!seen.has(id)) {
				seen.add(id);
				objectIds.push(id);
			}
		}
		byGroup.set(g.key, mine);
	}
	return { objectIds, byGroup, conflicts: [...conflicts].sort() };
}

// =============================================================================
// REVIEWED DOCUMENTS (the registry's 'reviewed documents' map, per connection)
// =============================================================================

/** The registry map of reviewed documents (adapters/connections.ts `reviewedDocuments`). */
export type ReviewedCache = Map<string, ReadonlySet<string>>;

/** One empty set for every connection without reviewed documents (stable, so memoised views do not recompute). */
const NONE_REVIEWED: ReadonlySet<string> = new Set<string>();

/**
 * A connection's reviewed documents.
 *
 * @param cache - The registry map.
 * @param connectionKey - The connection.
 * @returns The set (the same empty set when none).
 */
export function reviewedOf(cache: ReviewedCache, connectionKey: string): ReadonlySet<string> {
	return cache.get(connectionKey) ?? NONE_REVIEWED;
}

/**
 * Mark documents reviewed for a connection.
 *
 * @param cache - The registry map.
 * @param connectionKey - The connection.
 * @param objectIds - The documents.
 * @returns The connection's new set.
 */
export function markReviewed(cache: ReviewedCache, connectionKey: string, objectIds: readonly string[]): ReadonlySet<string> {
	const next = new Set(reviewedOf(cache, connectionKey));
	for (const id of objectIds) next.add(id);
	cache.set(connectionKey, next);
	return next;
}

/**
 * Take documents out of a connection's reviewed set ("Review again").
 *
 * @param cache - The registry map.
 * @param connectionKey - The connection.
 * @param objectIds - The documents.
 * @returns The connection's new set.
 */
export function unmarkReviewed(cache: ReviewedCache, connectionKey: string, objectIds: readonly string[]): ReadonlySet<string> {
	const next = new Set(reviewedOf(cache, connectionKey));
	for (const id of objectIds) next.delete(id);
	if (next.size === 0) cache.delete(connectionKey);
	else cache.set(connectionKey, next);
	return next;
}
