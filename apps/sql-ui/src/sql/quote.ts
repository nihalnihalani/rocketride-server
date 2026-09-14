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
// SQL — QUOTING (the one place a value becomes SQL text)
// =============================================================================
//
// Binding a value as a `$n` parameter is ALWAYS preferable: the driver never
// sees the value as syntax (see sql/paging.ts). quoteLiteral exists for the
// statements that cannot bind — catalog queries whose predicates the engines
// only accept as literals — and it is deliberately the only literal quoter in
// the app, so there is exactly one rule to review.
// =============================================================================

/**
 * Quote a string literal for embedding in a statement: single quotes with
 * doubled embedded quotes. The value is ALWAYS quoted, including when it
 * looks like a number — an unquoted all-digit table name would become a
 * number comparison against a text catalog column, which silently matches
 * the wrong rows on MySQL and raises a type error on Postgres.
 *
 * @param value - The literal value.
 * @returns The quoted literal.
 */
export function quoteLiteral(value: string): string {
	return "'" + value.replace(/'/g, "''") + "'";
}
