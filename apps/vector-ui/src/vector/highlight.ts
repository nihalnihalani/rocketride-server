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
// VECTOR - QUERY WORDS IN A CHUNK'S TEXT (pure)
// =============================================================================
//
// The chunk text panel marks the words of the active query in a chunk's full
// text. Matching is lexical and deliberately light: case-insensitive, whole
// words, a small suffix strip so "water", "waters" and "watering" meet, and
// the common English function words left out. Retrieval itself is by meaning,
// and the panel says so; these marks only help the eye.
//
// The answer is a list of text segments that joins back to the text exactly.
// Nothing here builds markup: the panel renders each marked segment as a
// <mark> element whose child is the segment's text, so a chunk holding '<b>'
// or '&amp;' shows those characters.
//
// Words are scanned character by character (letters of any script, digits,
// and an apostrophe between letters) rather than with Unicode property
// regexes, which some of the browsers this app supports lack.
// =============================================================================

/** Most characters of a chunk the panel shows. */
export const CHUNK_TEXT_MAX = 20000;

/** One run of text: a query word (mark) or anything between them. */
export interface ITextSegment {
	text: string;
	mark: boolean;
}

/** Common English function words: never marked. */
export const STOP_WORDS: ReadonlySet<string> = new Set(('a about above after again against all also am an and any are as at be because been before being below between both but by ' + 'can could did do does doing done down during each few for from further get gets got had has have having he her here hers ' + 'herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or ' + 'other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there ' + 'these they this those through to too under until up us very was we were what when where which while who whom whose why will ' + 'with would you your yours yourself yourselves shall may might must let lets').split(' '));

/**
 * Whether a character belongs to a word: a letter of any script, or a digit.
 *
 * @param ch - One character (one UTF-16 unit).
 * @returns True for a word character.
 */
function isWordChar(ch: string): boolean {
	if (ch >= '0' && ch <= '9') return true;
	return ch.toLowerCase() !== ch.toUpperCase();
}

/** Apostrophes that may join two parts of a word ("station's"). */
const APOSTROPHES = "'’";

/**
 * Split text into word and non-word runs.
 *
 * @param text - Any text.
 * @returns The runs, in order; they join back to `text`.
 */
function runs(text: string): Array<{ text: string; word: boolean }> {
	const out: Array<{ text: string; word: boolean }> = [];
	let i = 0;
	while (i < text.length) {
		const start = i;
		const word = isWordChar(text[i] as string);
		i += 1;
		while (i < text.length) {
			const ch = text[i] as string;
			if (word) {
				if (isWordChar(ch)) i += 1;
				else if (APOSTROPHES.includes(ch) && i + 1 < text.length && isWordChar(text[i + 1] as string)) i += 2;
				else break;
			} else if (isWordChar(ch)) break;
			else i += 1;
		}
		out.push({ text: text.slice(start, i), word });
	}
	return out;
}

/**
 * Drop one letter of a doubled final consonant ("runn" → "run"); l, s and z stay doubled.
 *
 * @param word - A word with a suffix removed.
 * @returns The word.
 */
function undouble(word: string): string {
	const last = word[word.length - 1];
	if (word.length > 2 && last === word[word.length - 2] && last !== undefined && !'aeiouylsz'.includes(last)) return word.slice(0, -1);
	return word;
}

/**
 * The light stem of a word: lower-cased, a possessive dropped, then one of
 * -ies, -ing, -ed, -es (after s, x, z, ch, sh) or a plural -s removed, and a
 * final e dropped, each only on words long enough for it to be a suffix.
 *
 * @param word - One word.
 * @returns Its stem.
 */
export function stem(word: string): string {
	let w = word.toLowerCase();
	if (w.length > 2 && (w.endsWith("'s") || w.endsWith('’s'))) w = w.slice(0, -2);
	if (w.length > 4 && w.endsWith('ies')) w = `${w.slice(0, -3)}y`;
	else if (w.length > 5 && w.endsWith('ing')) w = undouble(w.slice(0, -3));
	else if (w.length > 4 && w.endsWith('ed')) w = undouble(w.slice(0, -2));
	else if (w.length > 4 && /(ss|x|z|ch|sh)es$/.test(w)) w = w.slice(0, -2);
	else if (w.length > 3 && w.endsWith('s') && !/(ss|us|is)$/.test(w)) w = w.slice(0, -1);
	if (w.length > 4 && w.endsWith('e')) w = w.slice(0, -1);
	return w;
}

/**
 * The words of a query that the panel marks: stop-words and one-letter words
 * left out, each stem once, in the order they first appear.
 *
 * @param query - The active query, or null.
 * @returns The stems.
 */
export function queryTerms(query: string | null | undefined): string[] {
	if (!query) return [];
	const out: string[] = [];
	for (const run of runs(query)) {
		if (!run.word) continue;
		const lower = run.text.toLowerCase();
		const bare = lower.replace(/['’]s$/, '');
		if (bare.length < 2 || STOP_WORDS.has(lower) || STOP_WORDS.has(bare)) continue;
		const s = stem(lower);
		if (s.length >= 2 && !out.includes(s)) out.push(s);
	}
	return out;
}

/**
 * The query's words as typed (lower-cased), one per stem, in the order they
 * first appear: what the panel names when it counts the marks.
 *
 * @param query - The active query, or null.
 * @returns The words.
 */
export function queryWords(query: string | null | undefined): string[] {
	if (!query) return [];
	const stems = new Set<string>();
	const out: string[] = [];
	for (const run of runs(query)) {
		if (!run.word) continue;
		const lower = run.text.toLowerCase();
		const bare = lower.replace(/['’]s$/, '');
		if (bare.length < 2 || STOP_WORDS.has(lower) || STOP_WORDS.has(bare)) continue;
		const s = stem(lower);
		if (s.length < 2 || stems.has(s)) continue;
		stems.add(s);
		out.push(bare);
	}
	return out;
}

/**
 * Split a chunk's text into segments, marking every whole word whose stem is
 * one of the query's. Unmarked runs are merged; the segments join back to the
 * text exactly.
 *
 * @param text - The chunk's text.
 * @param query - The active query, or null.
 * @returns The segments (none for empty text).
 */
export function highlightSegments(text: string, query: string | null | undefined): ITextSegment[] {
	if (text === '') return [];
	const terms = new Set(queryTerms(query));
	if (terms.size === 0) return [{ text, mark: false }];
	const out: ITextSegment[] = [];
	let plain = '';
	for (const run of runs(text)) {
		if (run.word && terms.has(stem(run.text))) {
			if (plain !== '') out.push({ text: plain, mark: false });
			plain = '';
			out.push({ text: run.text, mark: true });
		} else plain += run.text;
	}
	if (plain !== '') out.push({ text: plain, mark: false });
	return out;
}

/**
 * How many words are marked.
 *
 * @param segments - The segments.
 * @returns The count.
 */
export function markedWords(segments: readonly ITextSegment[]): number {
	let n = 0;
	for (const s of segments) if (s.mark) n += 1;
	return n;
}

/**
 * Cut a chunk's text to what the panel shows.
 *
 * @param text - The full text.
 * @param max - Most characters (CHUNK_TEXT_MAX).
 * @returns The text and whether it was cut.
 */
export function clampText(text: string, max: number = CHUNK_TEXT_MAX): { text: string; truncated: boolean } {
	return text.length > max ? { text: text.slice(0, max), truncated: true } : { text, truncated: false };
}
