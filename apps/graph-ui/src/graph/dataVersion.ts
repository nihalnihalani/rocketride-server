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
// GRAPH - DATA VERSIONS (has something that can change data run on this connection?)
// =============================================================================
//
// A counter per connection that goes up whenever `execute` ran there (a success, or
// an outcome nobody saw because the app stopped waiting), from ANY document of the
// app: the write console is one document and the workbench's graph another, and the
// graph must find out that what it drew may no longer exist. It holds numbers only.
// =============================================================================

/** The counters. */
export interface IDataVersions {
	/** The current version of a connection (0 until a write ran). */
	get(key: string): number;
	/** Record that something may have changed. */
	bump(key: string): void;
	/** Subscribe to any change. */
	subscribe(listener: () => void): () => void;
}

/**
 * Create the counters.
 *
 * @returns A store with every connection at version 0.
 */
export function createDataVersions(): IDataVersions {
	const versions = new Map<string, number>();
	const listeners = new Set<() => void>();
	return {
		get: (key) => versions.get(key) ?? 0,
		bump(key) {
			versions.set(key, (versions.get(key) ?? 0) + 1);
			listeners.forEach((l) => l());
		},
		subscribe(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
	};
}

/**
 * Whether a finished run means data on the connection may have changed.
 *
 * `execute` is the only path that can write, so only the write console counts. A success did
 * whatever the statement says (the app does not trust its own text check to tell a write from a
 * read, so every success counts). A run the app stopped waiting for may still complete on the
 * database, so it counts too. A statement that failed was rolled back by the database and does not.
 *
 * @param mode - `read` for the workbench, `write` for the write console.
 * @param outcome - How the run ended.
 * @returns True when drawn ids may no longer mean what they did.
 */
export function mayHaveChangedData(mode: 'read' | 'write', outcome: string): boolean {
	return mode === 'write' && (outcome === 'rows' || outcome === 'affected' || outcome === 'abandoned');
}
