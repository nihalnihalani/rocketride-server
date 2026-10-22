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
// VECTOR - CONSOLE CONTROLLER (no React, no shell): stats, directory, chunks, removal
// =============================================================================
//
// One controller per open console. It owns the console's calls and their
// pacing, so the React view only renders its snapshot and forwards clicks:
//
//   STATS      `stats({mode:'full'})` on open, after a removal, after a
//              completed upload and on Refresh (after an upload or a write
//              the store's dialect is probed again too, deps.reprobe); `stats({mode:'quick'})` at
//              most every 15 s while the console is visible. A failure keeps
//              the last figures (the strip greys them) and says why; with no
//              figures yet, the full call is asked again every 15 s.
//   DIRECTORY  the auto-pager of vector/documents.ts: page after page in the
//              background while the console is visible; hidden, it pauses
//              (and sorts what is loaded); shown, it resumes at its cursor. A
//              refresh starts over and drops any page of the old listing.
//              With a scope, every page asks the store for its conditions
//              and its path box (setFilter); a new filter lists again from
//              the first page, the same one asks nothing, and refreshes keep
//              it. New path text alone keeps the rows when the store skipped
//              the path text (it would list the same ones).
//   CHUNKS     the selected document's chunks, a page at a time.
//   REMOVAL    requestRemove opens a confirmation and sends NOTHING; Cancel
//              sends nothing and says so; Confirm sends the batches once
//              (never retried), announces the rows the node removed, then
//              refreshes the stats in full and the directory. Nothing opens
//              or is sent while writes are not available, or while another
//              removal runs.
//
// Every call goes through injected functions, and time through an injected
// clock, so tests drive it without a browser.
// =============================================================================

import type { IChunkItem, IDocumentsFilter } from '../contract/types';
import { QUICK_STATS_INTERVAL_MS } from './budgets';
import { removalSummary, runRemoval } from './confirm';
import type { IRemoveTarget } from './confirm';
import { pagerApplyPage, pagerBegin, pagerFail, pagerInit, pagerLoadMore, pagerPause, pagerResume, pagerWantsPage } from './documents';
import type { IPagerState } from './documents';
import { filterKeys, keepListing, sameFilter } from './filters';
import type { IChunksPageView, IDocumentsPageView, IRemoveView, IStatsView } from './results';
import { statsRefreshPlan } from './stats';
import type { StatsTrigger } from './stats';
import { BUSY, CANCELLED_TEXT, failureText } from './wording';
import type { IFailureText } from './wording';

// =============================================================================
// TYPES
// =============================================================================

/** Time and timers (injected for tests). */
export interface IConsoleClock {
	now(): number;
	setTimer(fn: () => void, ms: number): unknown;
	clearTimer(handle: unknown): void;
}

/** What the controller calls. Each rejects with an ExplorerToolError on failure. */
export interface IConsoleDeps {
	stats(mode: 'full' | 'quick'): Promise<IStatsView>;
	/** One directory page; `filter` (the scope's conditions) is passed to the node when given. */
	documents(cursor: string | null, limit: number, filter?: IDocumentsFilter | null): Promise<IDocumentsPageView>;
	chunks(objectId: string, afterChunk: number, limit: number): Promise<IChunksPageView>;
	/** One remove_document batch. */
	remove(objectIds: string[]): Promise<IRemoveView>;
	/** Speak a short outcome through the polite live region. */
	announce(text: string): void;
	/** Documents that are no longer stored (the selection and the map forget them). */
	onRemoved?(objectIds: readonly string[]): void;
	/**
	 * Probe the store again (its `dialect`): after an upload completes and after a write, so what was read at
	 * discovery (an empty collection, no model or index yet) does not stay on screen. Fire and forget.
	 */
	reprobe?(): void;
	clock: IConsoleClock;
}

/** Page sizes and the write batch, from the node's limits. */
export interface IConsoleOptions {
	pageSize: number;
	chunkPage: number;
	writeBatch: number;
}

/** The statistics part of the snapshot. */
export interface IStatsSlot {
	view: IStatsView | null;
	status: 'idle' | 'loading' | 'ready' | 'error';
	error: IFailureText | null;
	/** Epoch ms of the last answer. */
	lastAt: number | null;
	/** The mode of the last answer. */
	mode: 'full' | 'quick' | null;
}

/** The chunk list of the selected document. */
export interface IChunksSlot {
	objectId: string | null;
	items: IChunkItem[];
	status: 'idle' | 'loading' | 'ready' | 'error';
	hasMore: boolean;
	nextAfter: number;
	total: number | null;
	error: IFailureText | null;
}

/** A confirmation waiting for the user. */
export interface IPendingRemoval {
	kind: 'single' | 'multi';
	targets: IRemoveTarget[];
}

/** The console's snapshot (replaced, never mutated). */
export interface IConsoleState {
	visible: boolean;
	stats: IStatsSlot;
	directory: IPagerState;
	chunks: IChunksSlot;
	confirm: IPendingRemoval | null;
	removal: { status: 'idle' | 'running' | 'done' | 'error'; message: string | null };
}

/** The controller. */
export interface IConsoleStore {
	getState(): IConsoleState;
	subscribe(listener: () => void): () => void;
	/** First load: full stats, the directory, and the quick-stats timer. */
	open(): void;
	/** The console was shown or hidden (another tab, the Map). */
	setVisible(visible: boolean): void;
	/** Whether removing is available (the console model's `writes`). */
	setWritesEnabled(enabled: boolean): void;
	/** Refresh: full stats and the directory from the start. */
	refresh(): void;
	/** An upload completed or documents changed elsewhere. */
	documentsChanged(): void;
	loadMoreDocuments(): void;
	retryDocuments(): void;
	/**
	 * The conditions every page of the directory asks the store for (the scope's, without the path box), or
	 * null for every document. New conditions list again from the first page; the same ones ask nothing.
	 * Before the console opens they are kept for its first listing.
	 */
	setFilter(filter: IDocumentsFilter | null): void;
	selectDocument(objectId: string | null): void;
	loadMoreChunks(): void;
	requestRemove(targets: readonly IRemoveTarget[]): void;
	cancelRemove(): void;
	confirmRemove(): Promise<void>;
	/** Stop every timer; later answers are dropped. */
	dispose(): void;
}

// =============================================================================
// FACTORY
// =============================================================================

const NO_CHUNKS: IChunksSlot = { objectId: null, items: [], status: 'idle', hasMore: false, nextAfter: -1, total: null, error: null };

/**
 * Create a console controller.
 *
 * @param deps - The calls, the announcer and the clock.
 * @param opts - Page sizes and the write batch.
 * @returns The controller.
 */
export function createConsoleStore(deps: IConsoleDeps, opts: IConsoleOptions): IConsoleStore {
	let state: IConsoleState = {
		visible: true,
		stats: { view: null, status: 'idle', error: null, lastAt: null, mode: null },
		directory: pagerInit(),
		chunks: NO_CHUNKS,
		confirm: null,
		removal: { status: 'idle', message: null },
	};
	const listeners = new Set<() => void>();
	let disposed = false;
	let writesEnabled = false;
	let timer: unknown = null;
	// Stats: the newest call wins; an older answer that arrives later is dropped.
	let statsSeq = 0;
	let statsApplied = 0;
	let statsInFlight = 0;
	// When the last stats call failed (null once one answers): before any answer, ticks retry in full.
	let statsFailedAt: number | null = null;
	// Directory: each listing is a run; a page of an older run never lands.
	let dirRun = 0;
	let pumping: number | null = null;
	// Chunks: each selection is a run.
	let chunkRun = 0;

	/** Replace the snapshot and notify. */
	function set(patch: Partial<IConsoleState>): void {
		if (disposed) return;
		state = { ...state, ...patch };
		for (const listener of [...listeners]) listener();
	}

	// ── Stats ────────────────────────────────────────────────────────────────

	/** Call stats and publish the answer (or the failure, keeping the last figures). */
	async function loadStats(mode: 'full' | 'quick'): Promise<void> {
		const seq = ++statsSeq;
		statsInFlight += 1;
		set({ stats: { ...state.stats, status: 'loading' } });
		try {
			const view = await deps.stats(mode);
			if (disposed || seq < statsApplied) return;
			statsApplied = seq;
			statsFailedAt = null;
			set({ stats: { view, status: 'ready', error: null, lastAt: deps.clock.now(), mode } });
		} catch (error) {
			if (disposed || seq < statsApplied) return;
			const text = failureText(error);
			if (text === null) return;
			statsFailedAt = deps.clock.now();
			set({ stats: { ...state.stats, status: 'error', error: text } });
		} finally {
			statsInFlight -= 1;
		}
	}

	/** Run the refresh plan for a trigger. */
	function planStats(trigger: StatsTrigger): void {
		const mode = statsRefreshPlan(trigger, { visible: state.visible, lastAt: state.stats.lastAt, failedAt: statsFailedAt, now: deps.clock.now(), inFlight: statsInFlight > 0 });
		if (mode !== null) void loadStats(mode);
	}

	/** (Re)arm the quick-stats timer. */
	function arm(): void {
		if (disposed) return;
		if (timer !== null) deps.clock.clearTimer(timer);
		timer = deps.clock.setTimer(() => {
			timer = null;
			if (disposed) return;
			planStats('tick');
			arm();
		}, QUICK_STATS_INTERVAL_MS);
	}

	// ── Directory ────────────────────────────────────────────────────────────

	/** Ask for pages while the listing wants them and the console is visible. */
	async function pump(run: number): Promise<void> {
		if (pumping === run) return;
		pumping = run;
		try {
			while (!disposed && run === dirRun && state.visible && pagerWantsPage(state.directory)) {
				let page: IDocumentsPageView;
				try {
					page = await deps.documents(state.directory.cursor, opts.pageSize, state.directory.filter);
				} catch (error) {
					if (disposed || run !== dirRun) return;
					const text = failureText(error);
					if (text !== null) set({ directory: pagerFail(state.directory, text) });
					return;
				}
				if (disposed || run !== dirRun) return;
				let next = pagerApplyPage(state.directory, page);
				if (!state.visible) next = pagerPause(next);
				set({ directory: next });
			}
		} finally {
			if (pumping === run) pumping = null;
		}
	}

	/** Start the listing over (with its filter unless another is given). */
	function startDirectory(filter: IDocumentsFilter | null = state.directory.filter): void {
		dirRun += 1;
		pumping = null;
		set({ directory: pagerBegin(state.directory, filter) });
		void pump(dirRun);
	}

	// ── Chunks ───────────────────────────────────────────────────────────────

	/** Load one page of the selected document's chunks. */
	async function loadChunks(run: number, objectId: string, afterChunk: number): Promise<void> {
		set({ chunks: { ...state.chunks, status: 'loading', error: null } });
		try {
			const page = await deps.chunks(objectId, afterChunk, opts.chunkPage);
			if (disposed || run !== chunkRun) return;
			const items = afterChunk < 0 ? page.items : [...state.chunks.items, ...page.items];
			set({ chunks: { objectId, items, status: 'ready', hasMore: page.hasMore, nextAfter: page.nextAfter, total: page.total, error: null } });
		} catch (error) {
			if (disposed || run !== chunkRun) return;
			const text = failureText(error);
			if (text !== null) set({ chunks: { ...state.chunks, status: 'error', error: text } });
		}
	}

	// ── Public ───────────────────────────────────────────────────────────────

	return {
		getState: () => state,
		subscribe(listener: () => void): () => void {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
		open(): void {
			planStats('open');
			startDirectory();
			arm();
		},
		setVisible(visible: boolean): void {
			if (visible === state.visible) return;
			if (!visible) {
				set({ visible, directory: pagerPause(state.directory) });
				return;
			}
			set({ visible, directory: state.directory.status === 'paused' ? pagerResume(state.directory) : state.directory });
			void pump(dirRun);
		},
		setWritesEnabled(enabled: boolean): void {
			writesEnabled = enabled;
			if (!enabled && state.confirm !== null) set({ confirm: null });
		},
		refresh(): void {
			planStats('manual');
			startDirectory();
		},
		documentsChanged(): void {
			planStats('upload');
			startDirectory();
			deps.reprobe?.();
		},
		loadMoreDocuments(): void {
			set({ directory: pagerLoadMore(state.directory) });
			void pump(dirRun);
		},
		retryDocuments(): void {
			set({ directory: pagerResume(state.directory) });
			void pump(dirRun);
		},
		setFilter(filter: IDocumentsFilter | null): void {
			const next = filter !== null && filterKeys(filter).length > 0 ? { ...filter } : null;
			if (sameFilter(next, state.directory.filter)) return;
			if (state.directory.status === 'idle') {
				set({ directory: { ...state.directory, filter: next } });
				return;
			}
			// Only the path box changed and the store skipped it: it would list the same rows again.
			const kept = keepListing(state.directory, next);
			if (kept !== null) {
				set({ directory: kept });
				return;
			}
			startDirectory(next);
		},
		selectDocument(objectId: string | null): void {
			chunkRun += 1;
			if (objectId === null) {
				set({ chunks: NO_CHUNKS });
				return;
			}
			set({ chunks: { ...NO_CHUNKS, objectId, status: 'loading' } });
			void loadChunks(chunkRun, objectId, -1);
		},
		loadMoreChunks(): void {
			const { objectId, hasMore, status, nextAfter } = state.chunks;
			if (objectId === null || !hasMore || status === 'loading') return;
			void loadChunks(chunkRun, objectId, nextAfter);
		},
		requestRemove(targets: readonly IRemoveTarget[]): void {
			if (!writesEnabled || targets.length === 0) return;
			// One removal at a time: nothing opens while one runs (a trash button outside the directory says why).
			if (state.removal.status === 'running') {
				deps.announce(BUSY.removing);
				return;
			}
			set({ confirm: { kind: targets.length === 1 ? 'single' : 'multi', targets: [...targets] } });
		},
		cancelRemove(): void {
			if (state.confirm === null) return;
			set({ confirm: null, removal: { status: 'idle', message: CANCELLED_TEXT } });
			deps.announce(CANCELLED_TEXT);
		},
		async confirmRemove(): Promise<void> {
			const pending = state.confirm;
			if (pending === null || !writesEnabled || state.removal.status === 'running') return;
			set({ confirm: null, removal: { status: 'running', message: null } });
			const outcome = await runRemoval(
				pending.targets.map((t) => t.objectId),
				(batch) => deps.remove(batch),
				opts.writeBatch
			);
			const message = removalSummary(outcome, pending.targets);
			set({ removal: { status: outcome.error ? 'error' : 'done', message } });
			deps.announce(message);
			const gone = [...outcome.removed.map((r) => r.objectId), ...outcome.notFound];
			if (gone.length > 0) {
				deps.onRemoved?.(gone);
				if (state.chunks.objectId !== null && gone.includes(state.chunks.objectId)) {
					chunkRun += 1;
					set({ chunks: NO_CHUNKS });
				}
			}
			if (outcome.batchesRun > 0) {
				planStats('write');
				startDirectory();
				deps.reprobe?.();
			}
		},
		dispose(): void {
			if (timer !== null) deps.clock.clearTimer(timer);
			timer = null;
			disposed = true;
			listeners.clear();
		},
	};
}
