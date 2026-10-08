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
// VECTOR-UI — MapView (the Map tab of a connection)
// =============================================================================
//
// The visual half of the explorer: a sample of the collection drawn as points,
// with the node's PCA as the first frame and two refined layouts computed in a
// worker (the seeded neighbour-graph layout, kept only when it keeps at least
// as much of each kNN neighbourhood as PCA; exact t-SNE up to 1,000 points).
// On top of it: hover, click with the 12 nearest chunks of the WHOLE
// collection, a text query placed as a star with rays to the TRUE top-k,
// answer sources and document chunk paths from the console, duplicates and
// outliers, the lasso, a keyboard path and the Table alternative.
//
// What it calls, always on the store node through the connection's Tools
// source (the Chat source on a read-only connection): `sample`, `project`,
// `neighbors`, `search`, `chunks`; and `embed` on the embedding node. The ONE
// raw vector the map handles is the query vector `embed` returns: it stays in
// this view (queryVector) and is sent unchanged to `project`, `search` and
// `neighbors` (scope scores); nothing under src/map receives it. The map never
// writes: removals are asked of the console (actions.requestRemove), which
// confirms them.
//
// Every action lands back in the console: Open document, Ask about these only,
// Remove, and the shared selection (focused chunk, highlights, lasso keys).
// =============================================================================

import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Banner, Button, EmptyState } from 'shell';
import { DuplicatesPanel } from '../components/DuplicatesPanel';
import { HeatStrip } from '../components/HeatStrip';
import { Legend } from '../components/Legend';
import { MapToolbar } from '../components/MapToolbar';
import { OutliersPanel } from '../components/OutliersPanel';
import { PointCanvas } from '../components/PointCanvas';
import { PointInspector } from '../components/PointInspector';
import { PointsTable } from '../components/PointsTable';
import type { ColourBy, IChunksResult, IEmbedResult, INeighborsResult, INeighborsScopeResult, IProjectItem, IProjectResult, ISampleInput, ISampleResult, ISearchResult, MapLayout, MapViewProps, SampleMode, VectorKey } from '../contract/types';
import { TSNE_MAX_POINTS } from '../map/budgets';
import { callTool } from '../map/calls';
import type { ToolAnswer } from '../map/calls';
import { forgetCameras } from '../map/cameraMemory';
import { colourPoints } from '../map/colours';
import { tweenPositions } from '../map/interaction';
import type { KeyAction } from '../map/interaction';
import { applyTransform, chunkPath, documentOf, hiddenMask, keyIndex, keyString, neighboursOf, normaliseLayout, pcaPositions, pointKey } from '../map/model';
import { createLatestQueue } from '../map/neighbours';
import type { IOverlayEnd, IPlace } from '../map/overlay';
import { centroidStar, placeProjected, querySims, raysFromSearch, resolveKeys, starFromProject, withSampleRetry } from '../map/queryProjection';
import type { IStar } from '../map/queryProjection';
import { spawnLayoutWorker } from '../map/spawnWorker';
import { MAP_STYLES } from '../map/styles';
import { readPalette } from '../map/tokens';
import type { IMapPalette } from '../map/tokens';
import { createLayoutClient } from '../map/workerClient';
import type { ILayoutClient } from '../map/workerClient';
import { BUSY, CENTROID_APPROX, LAYOUT_CANCELLED, LAYOUT_NOT_BETTER, MAP_UNAVAILABLE, QUERY_NEEDS_EMBED, QUERY_PLACED_APPROX, mapFailure, num, pointAnnouncement, sampleLabel } from '../map/wording';

export type { MapViewProps };

// =============================================================================
// CONSTANTS AND HOOKS
// =============================================================================

/** The first sample's seed (the toolbar's "New sample" moves it on). */
const DEFAULT_SEED = 7;

/** Neighbours listed for a clicked point. */
const NEIGHBOURS_K = 12;

/** Nearest sample points `project` returns per item. */
const PROJECT_M = 10;

/** Results of the true top-k search behind the rays. */
const RAYS_TOP_K = 10;

/** Duplicate pairs drawn at most (the panel lists them all). */
const MAX_DRAWN_DUPLICATES = 200;

/** Side panel tabs. */
type SideTab = 'point' | 'neighbours' | 'duplicates' | 'outliers' | 'selection' | 'heat';

const TABS: Array<{ id: SideTab; label: string }> = [
	{ id: 'point', label: 'Point' },
	{ id: 'neighbours', label: 'Neighbours' },
	{ id: 'duplicates', label: 'Duplicates' },
	{ id: 'outliers', label: 'Outliers' },
	{ id: 'selection', label: 'Selection' },
	{ id: 'heat', label: 'Heat strip' },
];

/**
 * The map palette, re-read when the shell switches theme (it writes tokens onto the root element).
 *
 * @returns The palette, or null outside a browser.
 */
function useMapPalette(): IMapPalette | null {
	const read = (): IMapPalette | null => {
		if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') return null;
		const style = getComputedStyle(document.documentElement);
		return readPalette((token) => style.getPropertyValue(token));
	};
	const [palette, setPalette] = useState<IMapPalette | null>(read);
	useEffect(() => {
		if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return undefined;
		const observer = new MutationObserver(() => setPalette(read()));
		observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
		setPalette(read());
		return () => observer.disconnect();
	}, []);
	return palette;
}

/**
 * Whether the system asks for reduced motion (tracks changes; Safari 13 has only addListener).
 *
 * @returns True under `prefers-reduced-motion: reduce`.
 */
function useReducedMotion(): boolean {
	const query = '(prefers-reduced-motion: reduce)';
	const [reduced, setReduced] = useState<boolean>(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches);
	useEffect(() => {
		if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
		const media = window.matchMedia(query);
		const onChange = (): void => setReduced(media.matches);
		onChange();
		if (typeof media.addEventListener === 'function') media.addEventListener('change', onChange);
		else media.addListener(onChange);
		return () => {
			if (typeof media.removeEventListener === 'function') media.removeEventListener('change', onChange);
			else media.removeListener(onChange);
		};
	}, []);
	return reduced;
}

/** The query placed on the map (never the vector itself). */
interface IQueryView {
	text: string;
	/** The `project({vector})` item (PCA coordinates and nearest sample points). */
	item: IProjectItem | null;
	/** Similarity of the query to every sample point. */
	sims: Float32Array | null;
	/** The true top-k of the whole collection. */
	search: ISearchResult | null;
	/** Lines for the legend (model mismatch, keyword fallback). */
	notes: string[];
}

/** A refined layout's raw positions. */
interface IRefined {
	layout: MapLayout;
	sampleId: string;
	positions: Float32Array;
}

/** The layout's state, for the toolbar and the lanes. */
type LayoutState = 'idle' | 'running' | 'done' | 'kept-pca' | 'cancelled' | 'refused' | 'failed' | 'unavailable';

// =============================================================================
// VIEW
// =============================================================================

/**
 * The Map tab.
 *
 * @param props - The connection model, its channels, the shared selection, console actions, visibility.
 * @returns The map.
 */
export function MapView(props: MapViewProps): React.ReactElement {
	const { model, channels, selection, actions, visible } = props;
	const state = useSyncExternalStore(selection.subscribe, selection.getState, selection.getState);
	const palette = useMapPalette();
	const reducedMotion = useReducedMotion();
	const limits = model.limits;
	const channel = channels.tools ?? channels.chat ?? channels.ingest;
	const embedChannel = channels.tools ?? channels.chat;
	const storeNode = model.nodes.store;
	const canSample = model.capabilities.sample !== false;
	const sampleModel = state.sampleModel !== null && state.connectionKey === model.connectionKey ? state.sampleModel : null;
	const sample = sampleModel?.result ?? null;
	const backend = model.connection.dialect?.backend ?? null;

	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [notice, setNotice] = useState<string | null>(null);
	const [layout, setLayout] = useState<MapLayout>('pca');
	const [refined, setRefined] = useState<IRefined | null>(null);
	const [layoutState, setLayoutState] = useState<LayoutState>('idle');
	const [layoutProgress, setLayoutProgress] = useState<number | null>(null);
	const [quality, setQuality] = useState<{ overlap: number; pcaOverlap: number } | null>(null);
	const [colourBy, setColourBy] = useState<ColourBy>('document');
	const [lasso, setLasso] = useState(false);
	const [table, setTable] = useState(false);
	const [threeD, setThreeD] = useState(false);
	const [tab, setTab] = useState<SideTab>('point');
	const [selected, setSelected] = useState<number | null>(null);
	const [focused, setFocused] = useState<number | null>(null);
	const [neighbours, setNeighbours] = useState<{ index: number; result: INeighborsResult } | null>(null);
	const [neighbourPins, setNeighbourPins] = useState<IProjectItem[]>([]);
	const [neighbourBusy, setNeighbourBusy] = useState(false);
	const [neighbourError, setNeighbourError] = useState<string | null>(null);
	const [chunkText, setChunkText] = useState<{ key: string; text: string } | null>(null);
	const [query, setQueryView] = useState<IQueryView | null>(null);
	const [heat, setHeat] = useState<{ objectId: string; chunks: number; scores: Array<{ chunkId: number; sim: number }> } | null>(null);
	const [fitToken, setFitToken] = useState(0);
	const [centreOn, setCentreOn] = useState<{ index: number; seq: number } | null>(null);
	const [pulse, setPulse] = useState(0);
	const [rendererKind, setRendererKind] = useState<'webgl' | 'canvas2d' | 'none'>('none');

	// The one query vector (from `embed`), kept here and sent only to project / search / neighbors.
	const queryVector = useRef<number[] | null>(null);
	const connectionRef = useRef(model.connectionKey);
	connectionRef.current = model.connectionKey;
	const autoSampled = useRef<string | null>(null);
	const seq = useRef(0);
	const clientRef = useRef<ILayoutClient | null>(null);
	if (clientRef.current === null) clientRef.current = createLayoutClient({ createWorker: spawnLayoutWorker });
	const client = clientRef.current;
	useEffect(() => () => client.dispose(), [client]);

	const neighbourQueue = useMemo(
		() =>
			channel === null
				? null
				: createLatestQueue<VectorKey, ToolAnswer<INeighborsResult>>((key) => callTool<INeighborsResult>(channel, 'neighbors', { key, k: Math.min(NEIGHBOURS_K, limits.neighbors_k_max), exclude_self: true }, { nodeId: storeNode })),
		[channel, storeNode, limits.neighbors_k_max],
	);
	useEffect(() => () => neighbourQueue?.dispose(), [neighbourQueue]);

	// -------------------------------------------------------------------------
	// Derived data
	// -------------------------------------------------------------------------

	const hidden = useMemo(() => (sampleModel ? hiddenMask(sampleModel) : null), [sampleModel]);
	const keyIdx = useMemo(() => (sample ? keyIndex(sample) : new Map<string, number>()), [sample]);
	const dims: 2 | 3 = threeD && layout === 'pca' ? 3 : 2;
	const raw = useMemo(() => {
		if (!sample) return new Float32Array(0);
		if (layout !== 'pca' && refined !== null && refined.sampleId === sample.sample_id && refined.layout === layout) return refined.positions;
		return pcaPositions(sample, dims);
	}, [sample, layout, refined, dims]);
	const frame = useMemo(() => normaliseLayout(raw, dims, hidden), [raw, dims, hidden]);

	// Layout changes tween (never under reduced motion).
	const [shown, setShown] = useState<Float32Array>(frame.positions);
	const shownRef = useRef(shown);
	shownRef.current = shown;
	useEffect(() => {
		const from = shownRef.current;
		const to = frame.positions;
		if (reducedMotion || from.length !== to.length || from.length === 0 || typeof requestAnimationFrame !== 'function') {
			setShown(to);
			return undefined;
		}
		let raf = 0;
		const started = performance.now();
		const step = (): void => {
			const t = Math.min(1, (performance.now() - started) / 450);
			setShown(t >= 1 ? to : tweenPositions(from, to, t));
			if (t < 1) raf = requestAnimationFrame(step);
		};
		raf = requestAnimationFrame(step);
		return () => cancelAnimationFrame(raf);
	}, [frame, reducedMotion]);

	const colouring = useMemo(() => (sample && palette ? colourPoints(sample, colourBy, palette, { querySims: query?.sims ?? null, hidden }) : null), [sample, palette, colourBy, query, hidden]);
	const highlight = state.connectionKey === model.connectionKey ? state.highlight : null;
	const place = useCallback((p: { x: number; y: number; z?: number } | null): IPlace | null => (p === null ? null : applyTransform(p, frame.transform)), [frame]);

	// Query star and rays (positions in raw layout units, then into the display frame).
	const star: IStar | null = useMemo(() => {
		if (!sample) return null;
		if (query?.item) {
			const s = starFromProject(query.item, layout, raw, dims);
			return s ? { ...applyTransform(s, frame.transform), exact: s.exact } : null;
		}
		if (highlight?.source === 'chat') {
			const res = resolveKeys(highlight.keys, keyIdx, sampleModel?.pinned ?? []);
			const s = centroidStar(res.points, raw, dims);
			return s ? { ...applyTransform(s, frame.transform), exact: false } : null;
		}
		return null;
	}, [sample, query, layout, raw, dims, frame, highlight, keyIdx, sampleModel]);

	const pinnedPlaces = useMemo(() => (sampleModel?.pinned ?? []).map((item) => place(placeProjected(item, layout, raw, dims))), [sampleModel, layout, raw, dims, place]);
	const rays: IOverlayEnd[] = useMemo(() => {
		if (!query?.search || !sampleModel) return [];
		return raysFromSearch(query.search, keyIdx, sampleModel.pinned).targets.flatMap((t): IOverlayEnd[] => {
			if (t.kind === 'point') return [{ index: t.index }];
			if (t.kind === 'pinned') {
				const at = pinnedPlaces[t.pinned];
				return at ? [{ at }] : [];
			}
			return [];
		});
	}, [query, sampleModel, keyIdx, pinnedPlaces]);

	const ringPoints = useMemo(() => {
		if (!highlight || highlight.source === 'lasso' || highlight.source === 'document') return [];
		return resolveKeys(highlight.keys, keyIdx, sampleModel?.pinned ?? []).points;
	}, [highlight, keyIdx, sampleModel]);
	const emphasised = useMemo(() => {
		if (!sample || !highlight || (highlight.source !== 'lasso' && highlight.source !== 'document')) return null;
		const mask = new Uint8Array(sample.n);
		for (const i of resolveKeys(highlight.keys, keyIdx, []).points) mask[i] = 1;
		return mask;
	}, [sample, highlight, keyIdx]);
	const documentPath = useMemo(() => {
		if (!sample || highlight?.source !== 'document' || highlight.keys.length === 0) return [];
		return chunkPath(sample, highlight.keys[0]?.[0] as string);
	}, [sample, highlight]);

	const neighbourEnds: IOverlayEnd[] = useMemo(() => {
		if (!neighbours || neighbours.index !== selected || !sampleModel) return [];
		const pins = new Map(neighbourPins.filter((p) => p.key).map((p) => [keyString(p.key![0], p.key![1]), p]));
		return neighbours.result.items.flatMap((item): IOverlayEnd[] => {
			const i = keyIdx.get(keyString(item.key[0], item.key[1]));
			if (i !== undefined) return [{ index: i }];
			const pin = pins.get(keyString(item.key[0], item.key[1]));
			const at = pin ? place(placeProjected(pin, layout, raw, dims)) : null;
			return at ? [{ at }] : [];
		});
	}, [neighbours, selected, sampleModel, neighbourPins, keyIdx, place, layout, raw, dims]);

	const overlay = useMemo(
		() => ({
			selected,
			focused,
			highlight: ringPoints,
			neighbours: neighbourEnds,
			hollow: [...pinnedPlaces, ...neighbourEnds.flatMap((e) => (e.at ? [e.at] : []))].filter((p): p is IPlace => p !== null),
			star,
			rays,
			chunkPath: documentPath,
			duplicates: (sample?.duplicates ?? []).slice(0, MAX_DRAWN_DUPLICATES).map((d): [number, number] => [d.a, d.b]),
			outliers: sample?.outliers ?? [],
			pulse,
		}),
		[selected, focused, ringPoints, neighbourEnds, pinnedPlaces, star, rays, documentPath, sample, pulse],
	);

	// -------------------------------------------------------------------------
	// Sampling
	// -------------------------------------------------------------------------

	/** Forget everything drawn on top of a sample. */
	const resetView = useCallback((keepQuery: boolean): void => {
		setLayout('pca');
		setRefined(null);
		setLayoutState('idle');
		setLayoutProgress(null);
		setQuality(null);
		setSelected(null);
		setFocused(null);
		setNeighbours(null);
		setNeighbourPins([]);
		setChunkText(null);
		setHeat(null);
		if (!keepQuery) {
			setQueryView(null);
			queryVector.current = null;
		}
	}, []);

	/** Draw a sample; resolves its id, or null on failure. */
	const drawSample = useCallback(
		async (opts: { n: number; mode: SampleMode; seed: number; includeKeys?: VectorKey[]; keepQuery?: boolean }): Promise<string | null> => {
			if (channel === null) return null;
			const key = model.connectionKey;
			const light = opts.mode === 'light';
			const input: ISampleInput = {
				n: opts.n,
				seed: opts.seed,
				strategy: 'stratified',
				mode: opts.mode,
				knn_k: Math.min(light ? 10 : 15, limits.knn_k_max),
				components: 3,
				duplicate_threshold: 0.97,
				include_text: !light,
				...(opts.includeKeys && opts.includeKeys.length > 0 ? { include_keys: opts.includeKeys } : {}),
			};
			client.cancel();
			setBusy(BUSY.sampling);
			setError(null);
			const answer = await callTool<ISampleResult>(channel, 'sample', input as Record<string, unknown>, { nodeId: storeNode, timeoutMs: limits.sample_budget_ms + 30_000 });
			if (connectionRef.current !== key) return null;
			setBusy(null);
			if (!answer.ok) {
				if (!answer.stale) setError(mapFailure(answer.code, answer.message));
				return null;
			}
			const result = answer.value;
			resetView(opts.keepQuery === true);
			selection.setSampleModel({ sampleId: result.sample_id, seed: opts.seed, mode: result.mode, receivedAt: Date.now(), result, pinned: [], removed: [] });
			setFitToken((t) => t + 1);
			actions.announce(sampleLabel(result));
			return result.sample_id;
		},
		[channel, model.connectionKey, limits, storeNode, client, resetView, selection, actions],
	);

	// First open: sample once per connection with the node's default size.
	useEffect(() => {
		if (!visible || !canSample || channel === null || sampleModel !== null || busy !== null) return;
		if (autoSampled.current === model.connectionKey) return;
		autoSampled.current = model.connectionKey;
		void drawSample({ n: Math.min(limits.sample_default, limits.sample_max), mode: 'detailed', seed: DEFAULT_SEED });
	}, [visible, canSample, channel, sampleModel, busy, model.connectionKey, limits, drawSample]);

	/** Draw the current sample again (same seed, pinned and highlighted keys kept): SAMPLE_EXPIRED. */
	const resample = useCallback(async (): Promise<string | null> => {
		if (!sampleModel) return null;
		const keep = [...sampleModel.pinned.flatMap((p) => (p.key ? [p.key] : [])), ...(highlight?.keys ?? [])].slice(0, limits.project_keys_max);
		return drawSample({ n: sampleModel.result.n_requested, mode: sampleModel.mode, seed: sampleModel.seed, includeKeys: keep.map((k) => [k[0], k[1]] as VectorKey), keepQuery: true });
	}, [sampleModel, highlight, limits.project_keys_max, drawSample]);

	/** Project keys outside the sample and pin them (hollow points). */
	const pinKeys = useCallback(
		async (keys: VectorKey[]): Promise<IProjectItem[]> => {
			if (channel === null || !sampleModel || keys.length === 0) return [];
			const answer = await withSampleRetry(sampleModel.sampleId, (id) => callTool<IProjectResult>(channel, 'project', { sample_id: id, keys: keys.slice(0, limits.project_keys_max), m: PROJECT_M }, { nodeId: storeNode }), resample);
			if (!answer.ok) {
				if (!answer.stale) setNotice(mapFailure(answer.code, answer.message));
				return [];
			}
			const items = answer.value.items.filter((item) => item.in_sample === null || item.in_sample === undefined);
			selection.addPinned(items);
			return items;
		},
		[channel, sampleModel, limits.project_keys_max, storeNode, resample, selection],
	);

	// -------------------------------------------------------------------------
	// Layouts
	// -------------------------------------------------------------------------

	const onLayout = useCallback(
		async (next: MapLayout): Promise<void> => {
			if (!sample || !sampleModel) return;
			setNotice(null);
			if (next === 'pca') {
				client.cancel();
				setLayout('pca');
				setLayoutState('idle');
				setLayoutProgress(null);
				setFitToken((t) => t + 1);
				return;
			}
			if (next === 'tsne' && sample.n > TSNE_MAX_POINTS) {
				setNotice(`t-SNE is limited to ${num(TSNE_MAX_POINTS)} points; this sample has ${num(sample.n)}. Draw a smaller sample or use the neighbour graph layout.`);
				return;
			}
			setThreeD(false);
			setLayoutState('running');
			setLayoutProgress(0);
			const sampleId = sample.sample_id;
			const outcome = await client.run({ sample, algorithm: next === 'tsne' ? 'tsne' : 'force', seed: sampleModel.seed, hidden }, (ticks, total) => setLayoutProgress(total > 0 ? ticks / total : null));
			setLayoutProgress(null);
			if (outcome.kind === 'superseded') return;
			if (outcome.kind === 'done') {
				const r = outcome.result;
				setQuality({ overlap: r.overlap, pcaOverlap: r.pcaOverlap });
				if (next === 'neighbour-graph' && r.overlap < r.pcaOverlap) {
					setLayout('pca');
					setLayoutState('kept-pca');
					setNotice(LAYOUT_NOT_BETTER);
					return;
				}
				setRefined({ layout: next, sampleId, positions: r.positions });
				setLayout(next);
				setLayoutState('done');
				setFitToken((t) => t + 1);
				actions.announce(`${next === 'tsne' ? 't-SNE' : 'Neighbour graph'} layout ready: it keeps ${Math.round(r.overlap * 100)}% of each point's neighbours, PCA ${Math.round(r.pcaOverlap * 100)}%.`);
				if (r.timedOut) setNotice('The layout stopped at its time budget and shows the positions it reached.');
				return;
			}
			setLayout('pca');
			setLayoutState(outcome.kind);
			setNotice(outcome.kind === 'cancelled' ? LAYOUT_CANCELLED : outcome.message);
		},
		[sample, sampleModel, client, hidden, actions],
	);

	const onCancel = useCallback((): void => {
		client.cancel();
	}, [client]);

	// -------------------------------------------------------------------------
	// Selection, neighbours, text
	// -------------------------------------------------------------------------

	const onPick = useCallback(
		async (index: number | null): Promise<void> => {
			setSelected(index);
			setFocused(index);
			setNeighbourError(null);
			if (index === null || !sample || neighbourQueue === null || channel === null) {
				setNeighbours(null);
				return;
			}
			const key = pointKey(sample, index);
			selection.focusChunk(key);
			setTab('point');
			// Light samples carry no text: fetch this chunk's.
			if (!sample.points.snip) {
				void callTool<IChunksResult>(channel, 'chunks', { object_id: key[0], after_chunk: key[1] - 1, limit: 1 }, { nodeId: storeNode }).then((answer) => {
					const item = answer.ok ? answer.value.items.find((c) => c.chunkId === key[1]) : undefined;
					if (item) setChunkText({ key: keyString(key[0], key[1]), text: item.content.length > 2000 ? `${item.content.slice(0, 2000)}…` : item.content });
				});
			}
			if (model.capabilities.neighbors === false) {
				setNeighbourError('This store cannot list the nearest chunks of the collection.');
				return;
			}
			setNeighbourBusy(true);
			const outcome = await neighbourQueue.request(key);
			if (outcome.status === 'superseded') return;
			setNeighbourBusy(false);
			if (outcome.status === 'failed' || !outcome.value.ok) {
				const answer = outcome.status === 'done' ? outcome.value : null;
				setNeighbourError(answer && !answer.ok ? mapFailure(answer.code, answer.message) : 'The neighbour search failed.');
				return;
			}
			const result = outcome.value.value;
			setNeighbours({ index, result });
			const outside = result.items.filter((item) => !keyIdx.has(keyString(item.key[0], item.key[1]))).map((item) => [item.key[0], item.key[1]] as VectorKey);
			setNeighbourPins(outside.length > 0 && model.capabilities.project !== false ? await pinKeysQuiet(outside) : []);
		},
		// pinKeysQuiet is defined below and stable for a sample.
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[sample, neighbourQueue, channel, selection, storeNode, model.capabilities, keyIdx],
	);

	/** Project keys without pinning them in the shared model (neighbour ends). */
	const pinKeysQuiet = async (keys: VectorKey[]): Promise<IProjectItem[]> => {
		if (channel === null || !sampleModel) return [];
		const answer = await callTool<IProjectResult>(channel, 'project', { sample_id: sampleModel.sampleId, keys: keys.slice(0, limits.project_keys_max), m: PROJECT_M }, { nodeId: storeNode });
		return answer.ok ? answer.value.items : [];
	};

	const selectKey = useCallback(
		(key: VectorKey): void => {
			const index = keyIdx.get(keyString(key[0], key[1]));
			if (index !== undefined) {
				void onPick(index);
				setCentreOn({ index, seq: ++seq.current });
			} else void pinKeys([[key[0], key[1]]]);
		},
		[keyIdx, onPick, pinKeys],
	);

	// The console focused a chunk (a "map" button): select it here too.
	useEffect(() => {
		if (!sample || state.chunk === null || state.connectionKey !== model.connectionKey) return;
		const index = keyIdx.get(keyString(state.chunk[0], state.chunk[1]));
		if (index === undefined || index === selected) return;
		void onPick(index);
		setCentreOn({ index, seq: ++seq.current });
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [state.chunk]);

	// Highlights from the console: pin what is outside the sample; chat sources pulse once.
	const lastHighlight = useRef<unknown>(null);
	useEffect(() => {
		if (!sample || !highlight || highlight === lastHighlight.current) return;
		lastHighlight.current = highlight;
		if (highlight.source === 'search' || highlight.source === 'lasso') return;
		const res = resolveKeys(highlight.keys, keyIdx, sampleModel?.pinned ?? []);
		if (res.outside.length > 0 && model.capabilities.project !== false) void pinKeys(res.outside);
		const first = res.points[0];
		if (first !== undefined) setCentreOn({ index: first, seq: ++seq.current });
		if (highlight.source === 'chat') {
			if (state.query && model.embed.enabled && embedChannel !== null && model.nodes.embed) void runQuery(state.query, false);
			if (!reducedMotion && typeof requestAnimationFrame === 'function') {
				const started = performance.now();
				const step = (): void => {
					const t = (performance.now() - started) / 900;
					setPulse(t >= 1 ? 0 : Math.sin(Math.PI * t));
					if (t < 1) requestAnimationFrame(step);
				};
				requestAnimationFrame(step);
			}
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [highlight, sample]);

	// -------------------------------------------------------------------------
	// Text query: embed -> project -> search
	// -------------------------------------------------------------------------

	const runQuery = async (text: string, setHighlightToTopK = true): Promise<void> => {
		if (!sampleModel || channel === null || embedChannel === null || !model.nodes.embed || !model.embed.enabled) {
			setError(QUERY_NEEDS_EMBED);
			return;
		}
		const key = model.connectionKey;
		setError(null);
		setNotice(null);
		setBusy(BUSY.embedding);
		const embedded = await callTool<IEmbedResult>(embedChannel, 'embed', { texts: [text], kind: 'query' }, { nodeId: model.nodes.embed, timeoutMs: 60_000 });
		if (connectionRef.current !== key) return;
		if (!embedded.ok) {
			setBusy(null);
			if (!embedded.stale) setError(mapFailure(embedded.code, embedded.message));
			return;
		}
		const vector = embedded.value.vectors[0];
		if (!Array.isArray(vector) || vector.length === 0) {
			setBusy(null);
			setError('The embedding node answered without a vector.');
			return;
		}
		queryVector.current = vector;
		setBusy(BUSY.projecting);
		const projected = model.capabilities.project === false ? null : await withSampleRetry(sampleModel.sampleId, (id) => callTool<IProjectResult>(channel, 'project', { sample_id: id, vector, m: PROJECT_M, with_similarities: true }, { nodeId: storeNode }), resample);
		const searched = await callTool<ISearchResult>(channel, 'search', { vector, top_k: Math.min(RAYS_TOP_K, limits.top_k_max), include_below_floor: true }, { nodeId: storeNode });
		if (connectionRef.current !== key) return;
		setBusy(null);
		const notes: string[] = [];
		if (projected && !projected.ok) notes.push(mapFailure(projected.code, projected.message));
		if (!searched.ok) notes.push(mapFailure(searched.code, searched.message));
		const search = searched.ok ? searched.value : null;
		if (search?.warnings?.includes('model_mismatch')) notes.push('The chat embedding model differs from the one this collection was built with; results may be meaningless.');
		if (search?.warnings?.includes('keyword_fallback')) notes.push('The store answered by keyword because the vector search failed.');
		const item = projected && projected.ok ? (projected.value.items[0] ?? null) : null;
		const current = selection.getState().sampleModel;
		const n = current?.result.n ?? sampleModel.result.n;
		const sims = projected && projected.ok ? querySims(projected.value, n) : null;
		if (layout !== 'pca' && item) notes.push(QUERY_PLACED_APPROX);
		setQueryView({ text, item, sims, search, notes });
		selection.setQuery(text);
		if (sims) setColourBy('query-similarity');
		if (search) {
			const top = search.results.flatMap((r) => (typeof r.metadata?.objectId === 'string' && typeof r.metadata?.chunkId === 'number' ? [[r.metadata.objectId, r.metadata.chunkId] as VectorKey] : []));
			if (setHighlightToTopK) selection.setHighlight({ source: 'search', keys: top });
			const outside = raysFromSearch(search, current ? keyIndex(current.result) : keyIdx, current?.pinned ?? []).outside;
			if (outside.length > 0) await pinKeys(outside);
			actions.announce(`Query placed on the map with rays to its ${num(top.length)} nearest chunks in the collection.`);
		}
	};

	// Heat strip: the selected point's document, every chunk scored against the query.
	useEffect(() => {
		if (tab !== 'heat' || !sample || selected === null || channel === null) return;
		const doc = documentOf(sample, selected);
		const vector = queryVector.current;
		if (!doc || vector === null) {
			setHeat(null);
			return;
		}
		const chunks = Math.min(doc.chunks ?? 0, limits.scope_keys_max);
		const ids = chunks > 0 ? Array.from({ length: chunks }, (_, c) => c) : chunkPath(sample, doc.objectId).map((i) => sample.points.chunk[i] as number);
		const keys = ids.map((c) => [doc.objectId, c] as VectorKey);
		let live = true;
		void callTool<INeighborsScopeResult>(channel, 'neighbors', { vector: queryVector.current, scope_keys: keys }, { nodeId: storeNode }).then((answer) => {
			if (!live) return;
			if (!answer.ok || !Array.isArray(answer.value.scores)) {
				setHeat(null);
				if (!answer.ok && !answer.stale) setNotice(mapFailure(answer.code, answer.message));
				return;
			}
			const scores = answer.value.scores;
			setHeat({ objectId: doc.objectId, chunks: Math.max(ids.length, (doc.chunks ?? 0)), scores: ids.map((c, t) => ({ chunkId: c, sim: scores[t] as number })) });
		});
		return () => {
			live = false;
		};
	}, [tab, sample, selected, channel, storeNode, limits.scope_keys_max, query]);

	// -------------------------------------------------------------------------
	// Lasso and keys
	// -------------------------------------------------------------------------

	const onLasso = useCallback(
		(indices: readonly number[]): void => {
			if (!sample) return;
			const keys = indices.map((i) => pointKey(sample, i));
			selection.setKeys(keys);
			selection.setHighlight({ source: 'lasso', keys });
			setLasso(false);
			setTab('selection');
			const docs = new Set(keys.map((k) => k[0])).size;
			actions.announce(`Selected ${num(keys.length)} points from ${num(docs)} documents.`);
		},
		[sample, selection, actions],
	);

	const onFocusMove = useCallback(
		(index: number): void => {
			if (!sample) return;
			setFocused(index);
			const doc = documentOf(sample, index);
			let shownCount = sample.n;
			if (hidden) for (const v of hidden) shownCount -= v;
			actions.announce(pointAnnouncement(index, shownCount, doc?.path ?? '?', sample.points.chunk[index] as number));
		},
		[sample, hidden, actions],
	);

	const onKeyAction = useCallback(
		(action: KeyAction): void => {
			if (action === 'inspect' && focused !== null) void onPick(focused);
			else if (action === 'clear') {
				setSelected(null);
				setFocused(null);
				setNeighbours(null);
				setLasso(false);
				selection.setKeys([]);
				if (state.highlight?.source === 'lasso') selection.setHighlight(null);
				actions.announce('Selection cleared.');
			} else if (action === 'lasso') setLasso((on) => !on);
		},
		[focused, onPick, selection, state.highlight, actions],
	);

	// -------------------------------------------------------------------------
	// Connection lifecycle
	// -------------------------------------------------------------------------

	useEffect(() => {
		// A new connection: nothing of the old one carries over.
		resetView(false);
		setError(null);
		setNotice(null);
		setBusy(null);
		client.cancel();
	}, [model.connectionKey, resetView, client]);

	useEffect(() => {
		// Sign-out or identity change: the console resets the selection to no connection.
		if (state.connectionKey === null) {
			forgetCameras();
			queryVector.current = null;
			client.cancel();
		}
	}, [state.connectionKey, client]);

	useEffect(() => {
		// A removed document's selected point goes.
		if (selected !== null && hidden && hidden[selected]) {
			setSelected(null);
			setNeighbours(null);
		}
	}, [hidden, selected]);

	// -------------------------------------------------------------------------
	// Render
	// -------------------------------------------------------------------------

	if (!canSample) {
		return (
			<div className="vector-map" style={{ ...MAP_STYLES.root, padding: 16 }} data-map-state="unavailable">
				<EmptyState title="No map for this store" description={MAP_UNAVAILABLE} />
			</div>
		);
	}
	if (channel === null) {
		return (
			<div className="vector-map" style={{ ...MAP_STYLES.root, padding: 16 }} data-map-state="unreachable">
				<EmptyState title="No running source reaches this store" description="Start the pipeline's Tools source (or its Chat source) and refresh to draw the map." />
			</div>
		);
	}

	const tsneReason = sample && sample.n > TSNE_MAX_POINTS ? `t-SNE is limited to ${num(TSNE_MAX_POINTS)} points; this sample has ${num(sample.n)}.` : null;
	const layoutBusy = layoutState === 'running' ? `${BUSY.layout}${layoutProgress !== null ? ` ${Math.round(layoutProgress * 100)}%` : ''}` : null;
	const pointCap = sample?.mode === 'light' ? limits.sample_max_light : limits.sample_max;
	const querySimsArray = query?.sims ? Array.from(query.sims) : null;
	const selectedKey = selected !== null && sample ? pointKey(sample, selected) : null;
	const selectedScore = selectedKey && query?.search ? (query.search.results.find((r) => r.metadata?.objectId === selectedKey[0] && r.metadata?.chunkId === selectedKey[1])?.score ?? null) : null;
	const lassoKeys = state.highlight?.source === 'lasso' ? state.highlight.keys : state.keys;
	const lassoDocs = Array.from(new Set(lassoKeys.map((k) => k[0])));
	const legendNotes = [...(query?.notes ?? []), ...(star && !star.exact && !query?.item ? [CENTROID_APPROX] : [])];
	const describe = (index: number): string => {
		if (!sample) return '';
		const doc = documentOf(sample, index);
		const snip = sample.points.snip?.[index];
		const sim = query?.sims ? ` · similarity ${(query.sims[index] ?? 0).toFixed(3)}` : '';
		return `${doc?.path ?? '?'} #${sample.points.chunk[index]}${sim}${snip ? ` — ${snip}` : ''}`;
	};

	return (
		<div
			className="vector-map"
			style={MAP_STYLES.root}
			data-map-state={sample ? 'ready' : busy ? 'sampling' : error ? 'error' : 'empty'}
			data-sample-mode={sample?.mode ?? ''}
			data-layout={layout}
			data-layout-state={layoutState}
			data-knn-overlap={quality ? quality.overlap.toFixed(4) : ''}
			data-pca-overlap={quality ? quality.pcaOverlap.toFixed(4) : ''}
			data-renderer={rendererKind}
			data-query-state={query === null ? 'none' : query.item || query.search ? 'placed' : 'failed'}
			data-rays={rays.length}
		>
			<MapToolbar
				limits={model.capabilities.sample_light === false ? { ...limits, sample_max_light: limits.sample_max } : limits}
				sample={sampleModel}
				busy={busy ?? layoutBusy}
				layout={layout}
				colourBy={colourBy}
				lasso={lasso}
				table={table}
				query={channel === null ? { enabled: false, reason: QUERY_NEEDS_EMBED } : model.embed}
				tsneReason={tsneReason}
				canCancel={layoutState === 'running'}
				threeD={threeD}
				onToggle3D={() => {
					setThreeD((on) => !on);
					setFitToken((t) => t + 1);
				}}
				onSample={(opts) => void drawSample(opts)}
				onLayout={(next) => void onLayout(next)}
				onCancel={onCancel}
				onColourBy={setColourBy}
				onQuery={(text) => void runQuery(text)}
				onToggleLasso={() => setLasso((on) => !on)}
				onFit={() => setFitToken((t) => t + 1)}
				onToggleTable={() => setTable((on) => !on)}
			/>
			{error ? (
				<div style={{ padding: '8px 10px' }}>
					<Banner variant="error">{error}</Banner>
				</div>
			) : null}
			{notice ? <p style={{ ...MAP_STYLES.note, padding: '0 10px' }}>{notice}</p> : null}
			{!sample ? (
				<div style={{ padding: 16 }}>
					<EmptyState
						title={busy ? BUSY.sampling : 'No sample drawn yet'}
						description={busy ? `Drawing up to ${num(Math.min(limits.sample_default, limits.sample_max))} points from the store.` : 'Draw a sample of the collection to see its points.'}
						action={busy ? undefined : <Button onClick={() => void drawSample({ n: Math.min(limits.sample_default, limits.sample_max), mode: 'detailed', seed: DEFAULT_SEED })}>Draw sample</Button>}
					/>
				</div>
			) : (
				<div style={MAP_STYLES.body}>
					<div style={MAP_STYLES.canvasColumn}>
						{table ? (
							<div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
								<PointsTable sample={sampleModel!} querySims={querySimsArray} selected={selected} onSelect={(i) => void onPick(i)} />
							</div>
						) : (
							<PointCanvas
								sample={sampleModel!}
								positions={shown}
								dimensions={dims}
								colours={colouring?.colours ?? []}
								rgba={colouring?.rgba ?? null}
								outlined={colouring?.outlined ?? null}
								hidden={hidden}
								emphasised={emphasised}
								overlay={overlay}
								palette={palette}
								pointSizePx={sample.mode === 'light' ? 3.5 : 5.5}
								cameraKey={model.connectionKey}
								fitToken={fitToken}
								centreOn={centreOn}
								visible={visible}
								selection={selection}
								lasso={lasso}
								describe={describe}
								onHover={() => undefined}
								onPick={(i) => void onPick(i)}
								onLasso={onLasso}
								onFocusMove={onFocusMove}
								onKeyAction={onKeyAction}
								onRendererInfo={setRendererKind}
							/>
						)}
						<Legend sample={sampleModel!} colourBy={colourBy} pointCap={pointCap} backend={backend} colouring={colouring} notes={legendNotes} />
					</div>
					<aside style={MAP_STYLES.side} aria-label="Map details">
						<div role="tablist" aria-label="Map details" style={MAP_STYLES.tabs}>
							{TABS.map((t) => (
								<button key={t.id} type="button" role="tab" aria-selected={tab === t.id} style={{ ...MAP_STYLES.tab, ...(tab === t.id ? MAP_STYLES.tabActive : {}) }} onClick={() => setTab(t.id)}>
									{t.label}
								</button>
							))}
						</div>
						<div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label} style={MAP_STYLES.sideBody}>
							{tab === 'point' ? (
								<PointInspector
									sample={sampleModel!}
									index={selected}
									neighbours={neighbours && neighbours.index === selected ? neighbours.result : null}
									querySim={selected !== null && query?.sims ? (query.sims[selected] ?? null) : null}
									score={selectedScore}
									text={selectedKey && chunkText?.key === keyString(selectedKey[0], selectedKey[1]) ? chunkText.text : null}
									busy={neighbourBusy ? BUSY.neighbours : null}
									error={neighbourError}
									writes={model.writes}
									onOpenDocument={(objectId, chunkId) => actions.openDocument(objectId, chunkId)}
									onFindSimilar={(key) => {
										selection.setHighlight({ source: 'neighbors', keys: neighbours?.result.items.map((item) => item.key) ?? [key] });
										selectKey(key);
									}}
									onSelectNeighbour={selectKey}
									onRemoveDocument={(objectId) => actions.requestRemove([objectId])}
								/>
							) : null}
							{tab === 'neighbours' ? (
								selected === null ? (
									<p style={MAP_STYLES.note}>Select a point to list its neighbours in this sample (the node&apos;s kNN graph).</p>
								) : (
									<ol aria-label="Neighbours in this sample" style={MAP_STYLES.list}>
										{neighboursOf(sample, selected).map((nb) => (
											<li key={nb.i} style={MAP_STYLES.row}>
												<button type="button" style={MAP_STYLES.linkButton} onClick={() => void onPick(nb.i)}>
													{documentOf(sample, nb.i)?.path ?? '?'} #{sample.points.chunk[nb.i]}
												</button>
												<span style={MAP_STYLES.small}> similarity {nb.sim.toFixed(3)}</span>
											</li>
										))}
									</ol>
								)
							) : null}
							{tab === 'duplicates' ? <DuplicatesPanel sample={sampleModel!} writes={model.writes} onSelect={(indices) => selection.setHighlight({ source: 'neighbors', keys: indices.map((i) => pointKey(sample, i)) })} onRemoveDocument={(objectId) => actions.requestRemove([objectId])} /> : null}
							{tab === 'outliers' ? <OutliersPanel sample={sampleModel!} onSelect={(i) => {
								void onPick(i);
								setCentreOn({ index: i, seq: ++seq.current });
							}} /> : null}
							{tab === 'selection' ? (
								lassoKeys.length === 0 ? (
									<p style={MAP_STYLES.note}>Turn on the lasso (L) and draw around points to select them.</p>
								) : (
									<section aria-label="Selected points">
										<p style={MAP_STYLES.text}>
											{num(lassoKeys.length)} points selected from {num(lassoDocs.length)} documents.
										</p>
										<div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
											<button type="button" style={MAP_STYLES.button} disabled={!model.chat.enabled} onClick={() => actions.askAbout(lassoDocs)}>
												Ask about these only
											</button>
											<button type="button" style={MAP_STYLES.button} disabled={!model.writes.enabled} onClick={() => actions.requestRemove(lassoDocs.slice(0, limits.write_ids_max))}>
												Remove these documents
											</button>
											<button
												type="button"
												style={MAP_STYLES.button}
												onClick={() => {
													const text = JSON.stringify(lassoKeys);
													if (typeof navigator !== 'undefined' && navigator.clipboard) void navigator.clipboard.writeText(text).then(() => actions.announce(`Copied ${num(lassoKeys.length)} keys.`));
												}}
											>
												Copy keys
											</button>
										</div>
										{!model.writes.enabled && model.writes.reason ? <p style={MAP_STYLES.note}>{model.writes.reason}</p> : null}
										{!model.chat.enabled && model.chat.reason ? <p style={MAP_STYLES.note}>{model.chat.reason}</p> : null}
									</section>
								)
							) : null}
							{tab === 'heat' ? (
								selected === null || query === null ? (
									<p style={MAP_STYLES.note}>Run a text query and select a point to see how similar every chunk of its document is to the query.</p>
								) : heat && heat.objectId === selectedKey?.[0] ? (
									<HeatStrip chunks={heat.chunks} scores={heat.scores} focused={selectedKey?.[1] ?? null} onSelectChunk={(chunkId) => actions.openDocument(heat.objectId, chunkId)} label="Similarity of each chunk to the query" />
								) : (
									<p style={MAP_STYLES.note} role="status">
										{BUSY.neighbours}
									</p>
								)
							) : null}
						</div>
					</aside>
				</div>
			)}
		</div>
	);
}

export default MapView;
