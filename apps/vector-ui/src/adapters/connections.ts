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
// ADAPTER - PER-CONNECTION OBJECTS (pure: no React, no shell values)
// =============================================================================
//
// What one open connection keeps while its console and document tabs come
// and go: the console controller (stats, directory, chunks, removal), the
// shared selection (vector/bridge), the console's tab (Console or Map) and
// the chat's scope ("Ask about these only"). Every one is built from the
// endpoint KEY plus refs: the controller reads the client and the live
// endpoint from `ctx` at call time, so a restarted pipeline (same key, new
// token) is called correctly without rebuilding anything.
//
// A change of identity clears them all (the app's cache registry): every
// controller is disposed (its late answers are dropped) and every selection
// is reset, so nothing of the previous identity's connections remains.
// =============================================================================

import { ExplorerToolError } from 'shared/explorer';
import type { IExplorerClient, IExplorerEndpoint } from 'shared/explorer';
import { createSelectionStore } from '../contract/bridge';
import type { IVectorLimits, SelectionStore } from '../contract/types';
import { CHUNKS_PAGE } from '../vector/budgets';
import { createConsoleStore } from '../vector/consoleStore';
import type { IConsoleClock, IConsoleStore } from '../vector/consoleStore';
import { DEFAULT_LIMITS } from '../vector/results';
import { fetchChunks, fetchDocumentsPage, fetchStats, removeDocumentsBatch } from './actions';
import { announcer, connectionCaches, vectorEndpoints } from './explorer';

/** A tiny external store of one value (useSyncExternalStore-compatible). */
export interface IValueStore<T> {
	get(): T;
	set(value: T): void;
	subscribe(listener: () => void): () => void;
}

/**
 * Create a value store.
 *
 * @param initial - The first value.
 * @returns The store.
 */
export function createValueStore<T>(initial: T): IValueStore<T> {
	let value = initial;
	const listeners = new Set<() => void>();
	return {
		get: () => value,
		set(next: T): void {
			if (Object.is(next, value)) return;
			value = next;
			for (const listener of [...listeners]) listener();
		},
		subscribe(listener: () => void): () => void {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
	};
}

/** The tabs of a console. */
export type ConsoleTab = 'console' | 'map';

/** What the controller reads at call time. */
export interface IConnectionContext {
	client: IExplorerClient | null;
	endpoint: IExplorerEndpoint;
	limits: IVectorLimits;
}

/** One open connection's objects. */
export interface IConnectionEntry {
	key: string;
	ctx: IConnectionContext;
	controller: IConsoleStore;
	selection: SelectionStore;
	tab: IValueStore<ConsoleTab>;
	chatScope: IValueStore<readonly string[] | null>;
	/** True once the console asked for its first stats and page. */
	opened: boolean;
}

/** The real clock. */
const REAL_CLOCK: IConsoleClock = {
	now: () => Date.now(),
	setTimer: (fn, ms) => setTimeout(fn, ms),
	clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

const entries = new Map<string, IConnectionEntry>();

/**
 * Build the controller of one connection, calling through the store's session at call time.
 *
 * @param entry - The entry (its ctx and selection).
 * @param clock - The clock (tests pass a manual one).
 * @returns The controller.
 */
function makeController(entry: Pick<IConnectionEntry, 'ctx' | 'selection'>, clock: IConsoleClock): IConsoleStore {
	const { ctx } = entry;
	const session = (tool: string) => {
		if (ctx.client === null) throw new ExplorerToolError({ kind: 'unavailable', tool, message: 'Not connected to the server. Reconnect, then refresh.' });
		return vectorEndpoints.session(ctx.client, ctx.endpoint);
	};
	return createConsoleStore(
		{
			stats: (mode) => fetchStats(session('stats'), ctx.endpoint.nodeId, mode),
			documents: (cursor, limit) => fetchDocumentsPage(session('documents'), ctx.endpoint.nodeId, { cursor, limit }),
			chunks: (objectId, afterChunk, limit) => fetchChunks(session('chunks'), ctx.endpoint.nodeId, { objectId, afterChunk, limit }),
			remove: (ids) => removeDocumentsBatch(session('remove_document'), ctx.endpoint.nodeId, ids),
			announce: (text) => announcer.announce(text),
			onRemoved: (ids) => {
				for (const id of ids) entry.selection.forgetDocument(id);
			},
			clock,
		},
		{
			get pageSize() {
				return ctx.limits.documents_page;
			},
			get chunkPage() {
				return Math.min(CHUNKS_PAGE, ctx.limits.chunks_page);
			},
			get writeBatch() {
				return ctx.limits.write_ids_max;
			},
		}
	);
}

/**
 * The objects of one connection, made on first use and kept until a change of identity.
 *
 * @param endpoint - The live endpoint (its key names the entry; the rest refreshes ctx).
 * @param client - The client, or null while disconnected.
 * @param limits - The node's limits (the dialect's, else the documented ones).
 * @param clock - The clock (tests pass a manual one).
 * @returns The entry.
 */
export function connectionEntry(endpoint: IExplorerEndpoint, client: IExplorerClient | null, limits: IVectorLimits = DEFAULT_LIMITS, clock: IConsoleClock = REAL_CLOCK): IConnectionEntry {
	let entry = entries.get(endpoint.key);
	if (!entry) {
		const ctx: IConnectionContext = { client, endpoint, limits };
		const selection = createSelectionStore(endpoint.key);
		const made: IConnectionEntry = { key: endpoint.key, ctx, selection, controller: undefined as unknown as IConsoleStore, tab: createValueStore<ConsoleTab>('console'), chatScope: createValueStore<readonly string[] | null>(null), opened: false };
		made.controller = makeController(made, clock);
		entries.set(endpoint.key, made);
		entry = made;
	}
	entry.ctx.client = client;
	entry.ctx.endpoint = endpoint;
	entry.ctx.limits = limits;
	return entry;
}

/**
 * The entry of a connection, if one was made.
 *
 * @param key - The endpoint key.
 * @returns The entry or undefined.
 */
export function existingEntry(key: string): IConnectionEntry | undefined {
	return entries.get(key);
}

/** How many connections have objects (tests). */
export function entryCount(): number {
	return entries.size;
}

connectionCaches.register('documents, auto-pager, chunks and removals', () => {
	for (const entry of entries.values()) entry.controller.dispose();
});
connectionCaches.register('selection and sample models', () => {
	for (const entry of entries.values()) entry.selection.reset(null);
});
connectionCaches.register('console tabs and chat scope', () => {
	entries.clear();
});
