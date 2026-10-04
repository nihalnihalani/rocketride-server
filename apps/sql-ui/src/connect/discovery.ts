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
// CONNECT — DISCOVERY (which components are SQL tool nodes)
// =============================================================================
//
// Discovery itself — reading `getTasks()`, keying connections by owner and run
// kind, grouping roles, probing — lives in shared/explorer/connect. All that is
// SQL Explorer's own is the answer to "which pipeline components expose the
// SQL tool surface".
// =============================================================================

/**
 * Pipeline component providers that expose the shared SQL tool surface
 * (execute / get_schema / dialect, inherited from DatabaseInstanceBase).
 * Extend this set when new relational nodes ship.
 */
export const DATABASE_PROVIDERS: ReadonlySet<string> = new Set([
	'db_mysql',
	'db_postgres',
	'db_clickhouse',
]);
