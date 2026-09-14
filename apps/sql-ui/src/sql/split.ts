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
// SQL — STATEMENT SPLITTER (dialect-aware scanner over a multi-statement buffer)
// =============================================================================
//
// Pure text scanning: no client, no session, no Monaco. The database node takes
// ONE statement per `execute` call, so a buffer holding several statements has
// to be split here before anything is sent.
//
// The scanner is hand-written rather than a regex because a `;` is only a
// separator in CODE: inside a string literal, a quoted identifier, a line or
// block comment, or a PostgreSQL dollar-quoted body it is ordinary text.
//
// NOT SUPPORTED — and deliberately so: MySQL's `DELIMITER` directive. A buffer
// that changes the statement terminator mid-file would need the scanner to
// interpret a client-side command, and a half-working implementation is worse
// than an honest gap: `DELIMITER $$` is scanned as ordinary code, so routines
// whose bodies contain `;` will split wrongly. Run those through the MySQL
// client instead.
// =============================================================================

import type { SqlDialect } from '../connect';

// =============================================================================
// TYPES
// =============================================================================

/** One statement found in a buffer, with the offsets it occupies. */
export interface IStatement {
	/** Zero-based position among the buffer's non-blank statements. */
	index: number;
	/** The statement text, trimmed, WITHOUT its terminating semicolon. */
	sql: string;
	/** Character offset of the first character of {@link sql} in the buffer. */
	start: number;
	/** Character offset one past the last character of {@link sql}. */
	end: number;
	/** One-based line holding {@link start}. */
	startLine: number;
	/** One-based line holding the last character of {@link sql}. */
	endLine: number;
}

/** The lexical traits that differ between the dialects the app speaks. */
interface IScanTraits {
	/** `#` starts a line comment (MySQL only; ClickHouse has `--` and `/* *\/`). */
	hashComments: boolean;
	/** `/* *\/` blocks nest (PostgreSQL only). */
	nestedBlockComments: boolean;
	/** `$tag$ ... $tag$` bodies are recognised (PostgreSQL only). */
	dollarQuotes: boolean;
	/** A backslash escapes the next character inside a string literal. */
	backslashEscapes: boolean;
}

/** What a stretch of the buffer is, lexically. */
type RegionKind = 'code' | 'string' | 'comment';

/** A maximal stretch of one lexical kind. */
interface IRegion {
	/** The lexical kind of this stretch. */
	kind: RegionKind;
	/** Start offset (inclusive). */
	start: number;
	/** End offset (exclusive). */
	end: number;
}

// =============================================================================
// DIALECT TRAITS
// =============================================================================

/**
 * Resolve the lexical traits of a dialect.
 *
 * ClickHouse takes `--` and block comments but NOT `#`, and it treats a
 * backslash inside a string literal as an escape. PostgreSQL is the only
 * dialect here with nested block comments and dollar-quoted bodies, and the
 * only one where a plain `'...'` literal does NOT honour backslash escapes
 * (`standard_conforming_strings`); its `E'...'` form is detected separately.
 *
 * @param dialect - The engine dialect.
 * @returns The traits the scanner applies.
 */
function traitsFor(dialect: SqlDialect): IScanTraits {
	return {
		hashComments: dialect === 'mysql',
		nestedBlockComments: dialect === 'postgres',
		dollarQuotes: dialect === 'postgres',
		backslashEscapes: dialect === 'mysql' || dialect === 'clickhouse',
	};
}

// =============================================================================
// SCANNER PRIMITIVES
// =============================================================================

/**
 * Whether the quote at `open` is preceded by PostgreSQL's `E` string prefix.
 *
 * @param sql - The buffer.
 * @param open - Offset of the opening single quote.
 * @returns True for `E'...'` / `e'...'`, where a backslash escapes.
 */
function isEscapeStringPrefix(sql: string, open: number): boolean {
	const prev = sql[open - 1];
	if (prev !== 'e' && prev !== 'E') return false;
	const before = sql[open - 2];
	return before === undefined || !/[A-Za-z0-9_$]/.test(before);
}

/**
 * Skip a delimited run (string literal or quoted identifier). The delimiter is
 * escaped by doubling it; a backslash escape is honoured when the dialect (or
 * the `E` prefix) says so. An unterminated run consumes the rest of the buffer.
 *
 * @param sql - The buffer.
 * @param open - Offset of the opening delimiter.
 * @param delim - The delimiter character.
 * @param backslashEscapes - Whether `\\x` escapes inside this run.
 * @returns The offset one past the closing delimiter.
 */
function skipDelimited(sql: string, open: number, delim: string, backslashEscapes: boolean): number {
	const n = sql.length;
	let i = open + 1;
	while (i < n) {
		const ch = sql[i];
		if (backslashEscapes && ch === '\\') {
			i += 2;
			continue;
		}
		if (ch === delim) {
			// A doubled delimiter is an escaped delimiter, not the end.
			if (sql[i + 1] === delim) {
				i += 2;
				continue;
			}
			return i + 1;
		}
		i += 1;
	}
	return n;
}

/**
 * Skip a `--` or `#` line comment up to (not including) the line break.
 *
 * @param sql - The buffer.
 * @param open - Offset of the first comment character.
 * @returns The offset of the line break, or the buffer length.
 */
function skipLineComment(sql: string, open: number): number {
	const nl = sql.indexOf('\n', open);
	return nl < 0 ? sql.length : nl;
}

/**
 * Skip a block comment, honouring nesting when the dialect supports it.
 * An unterminated comment consumes the rest of the buffer.
 *
 * @param sql - The buffer.
 * @param open - Offset of the opening slash.
 * @param nested - Whether nested block comments are recognised.
 * @returns The offset one past the closing marker.
 */
function skipBlockComment(sql: string, open: number, nested: boolean): number {
	const n = sql.length;
	let i = open + 2;
	let depth = 1;
	while (i < n) {
		if (nested && sql[i] === '/' && sql[i + 1] === '*') {
			depth += 1;
			i += 2;
			continue;
		}
		if (sql[i] === '*' && sql[i + 1] === '/') {
			depth -= 1;
			i += 2;
			if (depth === 0) return i;
			continue;
		}
		i += 1;
	}
	return n;
}

/** A dollar-quote opener: `$$` or `$tag$` with an identifier-shaped tag. */
const DOLLAR_TAG = /^\$([A-Za-z_][A-Za-z0-9_]*)?\$/;

/**
 * Skip a PostgreSQL dollar-quoted body. Returns `open` unchanged when the `$`
 * does not open one (a positional parameter such as `$1`, or a stray `$`), so
 * the caller can treat it as ordinary code.
 *
 * @param sql - The buffer.
 * @param open - Offset of the `$`.
 * @returns The offset one past the closing tag, or `open` when this is not a
 *          dollar quote.
 */
function skipDollarQuoted(sql: string, open: number): number {
	const match = DOLLAR_TAG.exec(sql.slice(open, open + 130));
	if (!match) return open;
	const tag = match[0];
	const close = sql.indexOf(tag, open + tag.length);
	return close < 0 ? sql.length : close + tag.length;
}

/**
 * Split the buffer into maximal code / string / comment stretches.
 *
 * This is the single place that knows SQL's lexical shape; the splitter, the
 * comment stripper and the top-level keyword search all read its output.
 *
 * @param sql - The buffer.
 * @param traits - The dialect's lexical traits.
 * @returns The regions, in order, covering the whole buffer.
 */
function scanRegions(sql: string, traits: IScanTraits): IRegion[] {
	const regions: IRegion[] = [];
	const n = sql.length;
	let codeStart = 0;
	let i = 0;

	while (i < n) {
		const ch = sql[i];
		let end = -1;
		let kind: RegionKind = 'code';

		if (ch === '\'') {
			end = skipDelimited(sql, i, '\'', traits.backslashEscapes || isEscapeStringPrefix(sql, i));
			kind = 'string';
		} else if (ch === '"') {
			end = skipDelimited(sql, i, '"', traits.backslashEscapes);
			kind = 'string';
		} else if (ch === '`') {
			end = skipDelimited(sql, i, '`', false);
			kind = 'string';
		} else if (ch === '-' && sql[i + 1] === '-') {
			end = skipLineComment(sql, i);
			kind = 'comment';
		} else if (traits.hashComments && ch === '#') {
			end = skipLineComment(sql, i);
			kind = 'comment';
		} else if (ch === '/' && sql[i + 1] === '*') {
			end = skipBlockComment(sql, i, traits.nestedBlockComments);
			kind = 'comment';
		} else if (traits.dollarQuotes && ch === '$') {
			const closed = skipDollarQuoted(sql, i);
			if (closed > i) {
				end = closed;
				kind = 'string';
			}
		}

		// Ordinary code character — keep accumulating the current code run.
		if (end < 0) {
			i += 1;
			continue;
		}
		if (i > codeStart) regions.push({ kind: 'code', start: codeStart, end: i });
		regions.push({ kind, start: i, end });
		i = end;
		codeStart = i;
	}

	if (n > codeStart) regions.push({ kind: 'code', start: codeStart, end: n });
	return regions;
}

// =============================================================================
// LINE INDEX
// =============================================================================

/**
 * Offsets at which each line starts (index 0 = line 1).
 *
 * @param sql - The buffer.
 * @returns The line-start offsets.
 */
function buildLineStarts(sql: string): number[] {
	const starts = [0];
	for (let i = 0; i < sql.length; i++) {
		if (sql[i] === '\n') starts.push(i + 1);
	}
	return starts;
}

/**
 * One-based line number for an offset.
 *
 * @param starts - Line-start offsets from {@link buildLineStarts}.
 * @param offset - The character offset.
 * @returns The one-based line number.
 */
function lineAt(starts: number[], offset: number): number {
	let low = 0;
	let high = starts.length - 1;
	while (low < high) {
		const mid = (low + high + 1) >> 1;
		if (starts[mid] <= offset) low = mid;
		else high = mid - 1;
	}
	return low + 1;
}

// =============================================================================
// PUBLIC API
// =============================================================================

/**
 * Same-length copy of the buffer with every string literal and comment blanked
 * to spaces, so a plain regex can search CODE without seeing quoted text.
 *
 * @param sql - The buffer.
 * @param traits - The dialect's lexical traits.
 * @returns A string of the same length holding only the code characters.
 */
function maskNonCode(sql: string, traits: IScanTraits): string {
	const regions = scanRegions(sql, traits);
	let out = '';
	for (const region of regions) {
		out += region.kind === 'code' ? sql.slice(region.start, region.end) : ' '.repeat(region.end - region.start);
	}
	return out;
}

/**
 * Replace every comment with a single space, leaving code and string literals
 * untouched. The space matters: `SELECT/**\/1` must not become `SELECT1`.
 *
 * @param sql - The buffer.
 * @param dialect - The engine dialect (decides `#` comments and nesting).
 * @returns The buffer with comments blanked out.
 */
export function stripSqlComments(sql: string, dialect: SqlDialect = 'unknown'): string {
	const regions = scanRegions(sql, traitsFor(dialect));
	let out = '';
	for (const region of regions) {
		out += region.kind === 'comment' ? ' ' : sql.slice(region.start, region.end);
	}
	return out;
}

/**
 * Whether `keyword` appears as a whole word in CODE at parenthesis depth 0.
 *
 * Used by the pattern check to tell `DELETE FROM t WHERE id = 1` (has a
 * top-level WHERE) from `DELETE FROM t` and from `DELETE FROM t WHERE` text
 * that only exists inside a literal or a subquery.
 *
 * @param sql - The statement.
 * @param keyword - The keyword to look for (case-insensitive).
 * @param dialect - The engine dialect.
 * @returns True when the keyword occurs unquoted, uncommented, outside parens.
 */
export function hasTopLevelKeyword(sql: string, keyword: string, dialect: SqlDialect = 'unknown'): boolean {
	const masked = maskNonCode(sql, traitsFor(dialect));
	const needle = new RegExp(`\\b${keyword}\\b`, 'gi');
	let match = needle.exec(masked);
	while (match) {
		// Parenthesis depth at the match: everything before it, in code only.
		let depth = 0;
		for (let i = 0; i < match.index; i++) {
			const ch = masked[i];
			if (ch === '(') depth += 1;
			else if (ch === ')') depth = Math.max(0, depth - 1);
		}
		if (depth === 0) return true;
		match = needle.exec(masked);
	}
	return false;
}

/**
 * Split a buffer into the statements it holds.
 *
 * Semicolons inside string literals, quoted identifiers, line comments, block
 * comments and PostgreSQL dollar-quoted bodies are ordinary characters.
 * Stretches that hold only whitespace and comments produce no statement, so a
 * trailing `;` or a closing comment never yields an empty run.
 *
 * @param sql - The buffer (one or more statements).
 * @param dialect - The engine dialect.
 * @returns The statements, in buffer order.
 */
export function splitStatements(sql: string, dialect: SqlDialect = 'unknown'): IStatement[] {
	const traits = traitsFor(dialect);
	const regions = scanRegions(sql, traits);
	const lineStarts = buildLineStarts(sql);
	const out: IStatement[] = [];
	let segStart = 0;

	/**
	 * Emit the segment `[segStart, segEnd)` when it holds more than whitespace
	 * and comments.
	 *
	 * @param segEnd - End offset of the segment (exclusive).
	 */
	const emit = (segEnd: number): void => {
		let start = segStart;
		let end = segEnd;
		while (start < end && /\s/.test(sql[start])) start += 1;
		while (end > start && /\s/.test(sql[end - 1])) end -= 1;
		if (end <= start) return;
		const text = sql.slice(start, end);
		if (!stripSqlComments(text, dialect).trim()) return;
		out.push({
			index: out.length,
			sql: text,
			start,
			end,
			startLine: lineAt(lineStarts, start),
			endLine: lineAt(lineStarts, end - 1),
		});
	};

	for (const region of regions) {
		if (region.kind !== 'code') continue;
		for (let i = region.start; i < region.end; i++) {
			if (sql[i] !== ';') continue;
			emit(i);
			segStart = i + 1;
		}
	}
	emit(sql.length);
	return out;
}

/**
 * The statement the cursor sits in.
 *
 * When the offset falls between statements (in the whitespace or comment after
 * a `;`) the PRECEDING statement is returned, so pressing Run with the caret
 * just after a semicolon re-runs what the caret is sitting behind. With no
 * preceding statement the first one is returned; an empty buffer returns null.
 *
 * @param sql - The buffer.
 * @param offset - Cursor offset in the buffer.
 * @param dialect - The engine dialect.
 * @returns The statement, or null when the buffer holds none.
 */
export function statementAtOffset(sql: string, offset: number, dialect: SqlDialect = 'unknown'): IStatement | null {
	const statements = splitStatements(sql, dialect);
	if (statements.length === 0) return null;
	let previous: IStatement | null = null;
	for (const statement of statements) {
		if (offset >= statement.start && offset <= statement.end) return statement;
		if (statement.end < offset) previous = statement;
	}
	return previous ?? statements[0];
}
