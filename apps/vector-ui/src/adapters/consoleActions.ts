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
// ADAPTER - CONSOLE ACTIONS (pure): what the map, the document tab and the panels ask the console
// =============================================================================
//
// ConsoleActions (src/contract/types.ts) are the only way another part of the
// app changes what the console shows: open a document tab, show keys on the
// map, ask to remove documents (the console confirms first; nothing is sent
// here), scope the next chat question, refresh after an upload, announce.
// =============================================================================

import type { ConsoleActions, HighlightSource, VectorKey } from '../contract/types';
import type { IRemoveTarget } from '../vector/confirm';
import type { IConnectionEntry } from './connections';

/** What the actions need from the app around them. */
export interface IConsoleActionDeps {
	/** Open (or focus) the document tab of one document. */
	openDocument(objectId: string, chunkId?: number): void;
	/**
	 * Bring this connection's console tab to the front (reopening it if it was closed). An action that changes
	 * what the console shows may come from a document tab, which would otherwise stay in front of it.
	 */
	showConsole(): void;
	/** Speak through the polite live region. */
	announce(text: string): void;
}

/**
 * The remove targets for objectIds: the directory's rows where it has them (path
 * and chunk count), else the objectId alone with an unknown count.
 *
 * @param entry - The connection.
 * @param objectIds - The documents.
 * @returns The targets, in the order asked.
 */
export function removeTargets(entry: Pick<IConnectionEntry, 'controller' | 'selection'>, objectIds: readonly string[]): IRemoveTarget[] {
	const rows = new Map(entry.controller.getState().directory.rows.map((row) => [row.objectId, row]));
	const selected = entry.selection.getState().document;
	return objectIds.map((objectId) => {
		const row = rows.get(objectId);
		if (row) return { objectId, path: row.path, chunks: row.chunks };
		return { objectId, path: selected?.objectId === objectId ? selected.path : objectId, chunks: null };
	});
}

/**
 * The console's actions for one connection.
 *
 * @param entry - The connection's objects.
 * @param deps - Opening a document tab, fronting the connection's console and announcing.
 * @returns The actions.
 */
export function makeConsoleActions(entry: Pick<IConnectionEntry, 'controller' | 'selection' | 'tab' | 'chatScope'>, deps: IConsoleActionDeps): ConsoleActions {
	return {
		openDocument: (objectId: string, chunkId?: number) => deps.openDocument(objectId, chunkId),
		showOnMap: (keys: readonly VectorKey[], source: HighlightSource) => {
			entry.selection.setHighlight({ source, keys });
			entry.tab.set('map');
			deps.showConsole();
		},
		requestRemove: (objectIds: readonly string[]) => entry.controller.requestRemove(removeTargets(entry, objectIds)),
		askAbout: (objectIds: readonly string[]) => {
			entry.chatScope.set(objectIds.length === 0 ? null : [...objectIds]);
			entry.tab.set('console');
			deps.showConsole();
		},
		documentsChanged: () => entry.controller.documentsChanged(),
		announce: (text: string) => deps.announce(text),
	};
}
