// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// SCOPE AND FILTERS (pure): conditions, the wire filter, matching, the scope's ids and words
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { IDocumentItem, IDocumentsFilter, IScopeState } from '../src/contract/types';
import { DOCUMENTS_FILTER_KEYS } from '../src/contract/types';
import { pagerApplyPage, pagerBegin, pagerInit } from '../src/vector/documents';
import type { IPagerState } from '../src/vector/documents';
import { EMPTY_FILTER, FILTER_TEXT_MAX, clientKeys, conditionAvailability, conditionLabel, dateToIso, describeFilter, fromDocumentsFilter, listingFilter, matches, parseFilter, removeCondition, resolveScope, sameFilter, scopeAvailability, scopeFromFilter, scopeWith, filterOf, withText, scopeObjectIds, scopeStatusText, scopeStripText, setCondition, toDocumentsFilter, tooLargeText, validateFilter } from '../src/vector/filters';
import type { IFilter } from '../src/vector/filters';
import { readDocumentsPage, readStats } from '../src/vector/results';
import { fixture } from './support/fixtures';

/** A synthetic document row. */
function doc(objectId: string, path: string, over: Partial<IDocumentItem> = {}): IDocumentItem {
	return { objectId, path, chunks: 3, has_first_chunk: true, tables: 0, deleted: false, nodeId: 'chunk_1', size: null, modifyTime: null, ingestedAt: null, pointId: null, ...over };
}

/** The Windows, POSIX, share and bare-name rows. */
const PATHS: IDocumentItem[] = readDocumentsPage(fixture('documents_windows_and_posix_paths')).items;

/** The paths of the rows a wire filter matches. */
function pathsOf(rows: readonly IDocumentItem[], filter: IDocumentsFilter, keys?: readonly string[]): string[] {
	return rows.filter((row) => matches(row, filter, keys)).map((row) => row.path);
}

/** A complete, settled listing of these rows (as one page). */
function listed(rows: IDocumentItem[], filter: IDocumentsFilter | null = null, answer: Record<string, unknown> = {}): IPagerState {
	return pagerApplyPage(pagerBegin(pagerInit(), filter), readDocumentsPage({ success: true, items: rows, next_cursor: null, total: rows.length, counts_exact: true, distinct: true, sorted: true, caveats: [], ...answer }));
}

/** A scope over a filter, applied everywhere, not resolved yet. */
function scopeOf(filter: IDocumentsFilter, applyTo: Partial<IScopeState['applyTo']> = {}): IScopeState {
	return { filter, label: describeFilter(filter), objectIds: null, overflow: null, applyTo: { documents: true, map: true, search: true, chat: true, ...applyTo } };
}

// =============================================================================
// CONDITIONS
// =============================================================================

test('one condition per kind: adding one of a kind already set replaces it, removing takes it out, the path box is kept', () => {
	let filter: IFilter = { ...EMPTY_FILTER, text: 'falcon' };
	filter = setCondition(filter, { kind: 'folder', prefix: 'C:/demo/' });
	filter = setCondition(filter, { kind: 'fileType', types: ['md', 'PDF', 'md'] });
	filter = setCondition(filter, { kind: 'folder', prefix: 'C:/demo/handbooks/' });
	assert.deepEqual(
		filter.conditions.map((c) => conditionLabel(c)),
		['folder is under C:/demo/handbooks/', 'type is md or pdf']
	);
	assert.equal(filter.text, 'falcon');
	filter = removeCondition(filter, 'folder');
	assert.deepEqual(
		filter.conditions.map((c) => c.kind),
		['fileType']
	);
	assert.equal(removeCondition(filter, 'chunks'), filter, 'removing a kind that is not set changes nothing');
});

test('every condition says what it keeps, in words', () => {
	assert.equal(conditionLabel({ kind: 'folder', prefix: 'C:\\Users\\demo\\' }), 'folder is under C:\\Users\\demo\\');
	assert.equal(conditionLabel({ kind: 'fileType', types: ['pdf'] }), 'type is pdf');
	assert.equal(conditionLabel({ kind: 'fileType', types: ['md', 'pdf', 'txt'] }), 'type is md, pdf or txt');
	assert.equal(conditionLabel({ kind: 'ingestedAfter', at: '2026-10-01T00:00:00Z' }), 'ingested on or after 2026-10-01');
	assert.equal(conditionLabel({ kind: 'ingestedBefore', at: '2026-10-08T00:00:00Z' }), 'ingested before 2026-10-08');
	assert.equal(conditionLabel({ kind: 'chunks', min: 2, max: 10 }), '2 to 10 chunks');
	assert.equal(conditionLabel({ kind: 'chunks', min: 64, max: null }), 'at least 64 chunks');
	assert.equal(conditionLabel({ kind: 'chunks', min: null, max: 1 }), 'at most 1 chunk');
	assert.equal(conditionLabel({ kind: 'hasTables', value: true }), 'has tables');
	assert.equal(conditionLabel({ kind: 'hasTables', value: false }), 'has no tables');
	assert.equal(conditionLabel({ kind: 'firstChunk', present: false }), 'missing first chunk');
	assert.equal(conditionLabel({ kind: 'firstChunk', present: true }), 'has its first chunk');
	assert.equal(describeFilter({ path_prefix: 'C:/demo/handbooks/', file_types: ['md'], path_contains: 'fal' }), "folder is under C:/demo/handbooks/ · type is md · path contains 'fal'");
	assert.equal(describeFilter({}), 'every document');
});

test('dates from the date inputs become UTC midnight', () => {
	assert.equal(dateToIso('2026-10-01'), '2026-10-01T00:00:00Z');
	assert.equal(dateToIso('2026-13-01'), null);
	assert.equal(dateToIso(''), null);
});

// =============================================================================
// THE WIRE FILTER (contract section 4.4-A)
// =============================================================================

test('toDocumentsFilter sends only the keys that are set, the path box as path_contains, and nothing for no condition', () => {
	const filter: IFilter = {
		conditions: [
			{ kind: 'folder', prefix: 'C:/demo/handbooks/' },
			{ kind: 'fileType', types: ['md', 'pdf'] },
			{ kind: 'ingestedAfter', at: '2026-10-01T00:00:00Z' },
			{ kind: 'chunks', min: 1, max: null },
			{ kind: 'firstChunk', present: true },
			{ kind: 'hasTables', value: false },
		],
		text: '  hand ',
	};
	assert.deepEqual(toDocumentsFilter(filter), { path_prefix: 'C:/demo/handbooks/', file_types: ['md', 'pdf'], ingested_after: '2026-10-01T00:00:00Z', min_chunks: 1, has_first_chunk: true, has_tables: false, path_contains: 'hand' });
	assert.deepEqual(toDocumentsFilter({ conditions: [], text: '' }), {});
	for (const key of Object.keys(toDocumentsFilter(filter))) assert.ok((DOCUMENTS_FILTER_KEYS as readonly string[]).includes(key), key);
	assert.deepEqual(listingFilter(toDocumentsFilter(filter)), { path_prefix: 'C:/demo/handbooks/', file_types: ['md', 'pdf'], ingested_after: '2026-10-01T00:00:00Z', min_chunks: 1, has_first_chunk: true, has_tables: false }, 'the listing asks for the conditions; the path box filters what is loaded');
	assert.equal(listingFilter({ path_contains: 'x' }), null, 'the path box alone asks the store for nothing');
});

test('parseFilter reads the wire shape back into conditions (round trip), and refuses what the node would refuse', () => {
	const wire: IDocumentsFilter = { path_prefix: 'C:/demo/', file_types: ['md'], ingested_after: '2026-10-01T00:00:00Z', ingested_before: '2026-10-09T00:00:00Z', min_chunks: 2, max_chunks: 40, has_first_chunk: false, has_tables: true, path_contains: 'guide' };
	const parsed = parseFilter(wire);
	assert.ok('filter' in parsed);
	assert.deepEqual(toDocumentsFilter(parsed.filter), wire);
	assert.deepEqual(fromDocumentsFilter({ path_prefix: null, file_types: null, min_chunks: 3 }).conditions, [{ kind: 'chunks', min: 3, max: null }], 'nulls are "not filtered by it"');

	const refused = (value: unknown): string => {
		const out = parseFilter(value);
		assert.ok('error' in out, JSON.stringify(value));
		return out.error;
	};
	assert.match(refused({ colour: 'red' }), /colour/);
	assert.match(refused({ ingested_after: '1st of October' }), /ISO-8601/);
	assert.match(refused({ path_prefix: 'x'.repeat(FILTER_TEXT_MAX + 1) }), /1,024/);
	assert.match(refused({ path_contains: 'x'.repeat(FILTER_TEXT_MAX + 1) }), /1,024/);
	assert.match(refused({ min_chunks: 5, max_chunks: 2 }), /at most/);
	assert.match(refused({ min_chunks: -1 }), /whole number/);
	assert.match(refused({ file_types: ['.md'] }), /extension/);
	assert.match(refused({ has_tables: 'yes' }), /true or false/);
	assert.match(refused('folder'), /object/);
	assert.equal(validateFilter({ path_prefix: 'C:/demo/' }), null);
});

test('sameFilter compares meaning, not key order or empty keys', () => {
	assert.ok(sameFilter({ path_prefix: 'a', file_types: ['md', 'pdf'] }, { file_types: ['pdf', 'md'], path_prefix: 'a', min_chunks: null }));
	assert.ok(!sameFilter({ path_prefix: 'a' }, { path_prefix: 'b' }));
	assert.ok(sameFilter(null, {}));
});

// =============================================================================
// MATCHING (what the app filters here)
// =============================================================================

test('folder is under: the stored path starts with the prefix, case and separators as stored (Windows, POSIX, shares)', () => {
	assert.deepEqual(pathsOf(PATHS, { path_prefix: 'C:\\Users\\demo\\' }), ['C:\\Users\\demo\\Documents\\plan.docx']);
	assert.deepEqual(pathsOf(PATHS, { path_prefix: 'C:/demo/' }), ['C:/demo/handbooks/falcon_handbook.md']);
	assert.deepEqual(pathsOf(PATHS, { path_prefix: '/home/' }), ['/home/demo/notes/todo.md']);
	assert.deepEqual(pathsOf(PATHS, { path_prefix: '\\\\fileserver\\share\\' }), ['\\\\fileserver\\share\\policies\\leave.pdf']);
	assert.deepEqual(pathsOf(PATHS, { path_prefix: 'c:/demo/' }), [], 'case-sensitive, as the store compares');
});

test('file type: by the extension of the file name, ignoring case; bare names count', () => {
	assert.deepEqual(pathsOf(PATHS, { file_types: ['pdf'] }), ['D:/archive/2024/minutes.pdf', '\\\\fileserver\\share\\policies\\leave.pdf', 'report.pdf', 'report.pdf', 'Uploaded/naïve résumé.pdf']);
	assert.deepEqual(pathsOf(PATHS, { file_types: ['MD', 'docx'] }), ['C:\\Users\\demo\\Documents\\plan.docx', 'C:/demo/handbooks/falcon_handbook.md', '/home/demo/notes/todo.md']);
	assert.deepEqual(pathsOf([doc('a', 'C:/x.md/notes')], { file_types: ['md'] }), [], 'a folder named like a type is not the file type');
	assert.deepEqual(pathsOf([doc('a', 'README.MD')], { file_types: ['md'] }), ['README.MD']);
});

test('ingest dates, chunk counts, tables, first chunk and the path box; a value the store did not give never matches', () => {
	const rows = [doc('a', 'C:/demo/a.md', { ingestedAt: '2026-10-01T09:00:00Z', chunks: 1, tables: 0 }), doc('b', 'C:/demo/b.md', { ingestedAt: '2026-10-08T18:20:11Z', chunks: 64, tables: 2 }), doc('c', 'C:/demo/c.md', { ingestedAt: null, chunks: null, tables: null, has_first_chunk: false })];
	const ids = (filter: IDocumentsFilter) => rows.filter((r) => matches(r, filter)).map((r) => r.objectId);
	assert.deepEqual(ids({ ingested_after: '2026-10-02T00:00:00Z' }), ['b']);
	assert.deepEqual(ids({ ingested_before: '2026-10-02T00:00:00Z' }), ['a']);
	assert.deepEqual(ids({ ingested_after: '2026-10-08T18:20:11Z' }), ['b'], 'after is inclusive');
	assert.deepEqual(ids({ min_chunks: 2 }), ['b']);
	assert.deepEqual(ids({ max_chunks: 1 }), ['a']);
	assert.deepEqual(ids({ min_chunks: 1, max_chunks: 64 }), ['a', 'b']);
	assert.deepEqual(ids({ has_tables: true }), ['b']);
	assert.deepEqual(ids({ has_tables: false }), ['a']);
	assert.deepEqual(ids({ has_first_chunk: false }), ['c']);
	assert.deepEqual(ids({ has_first_chunk: true }), ['a', 'b']);
	assert.deepEqual(ids({ path_contains: 'B.MD' }), ['b'], 'the path box ignores case');
	assert.deepEqual(ids({}), ['a', 'b', 'c']);
	assert.deepEqual(
		rows.filter((r) => matches(r, { min_chunks: 2, has_first_chunk: false }, ['has_first_chunk'])).map((r) => r.objectId),
		['c'],
		'only the keys asked for are applied here'
	);
});

test('clientKeys: what the app filters itself after the store answered server, partial or none (or an older node said nothing)', () => {
	const sent: IDocumentsFilter = { path_prefix: 'C:/demo/', ingested_after: '2026-10-01T00:00:00Z', path_contains: 'fal' };
	assert.deepEqual(clientKeys(sent, 'server', []), ['path_contains']);
	assert.deepEqual(clientKeys(sent, 'partial', ['ingested_after']), ['ingested_after', 'path_contains']);
	assert.deepEqual(clientKeys(sent, 'none', ['path_prefix', 'ingested_after']), ['path_prefix', 'ingested_after', 'path_contains']);
	assert.deepEqual(clientKeys(sent, null, []), ['path_prefix', 'ingested_after', 'path_contains'], 'not asked of the store, or an older node: everything here');
});

test('scopeObjectIds: every matching document once, null ids with the count above the cap', () => {
	const rows = [doc('a', 'C:/demo/a.md', { chunks: 4 }), doc('b', 'C:/demo/b.md', { chunks: 6 }), doc('c', 'D:/c.md'), doc('a', 'C:/demo/a.md')];
	assert.deepEqual(scopeObjectIds(rows, { path_prefix: 'C:/demo/' }, 2), { ids: ['a', 'b'], overflow: null, count: 2, chunks: 10 });
	assert.deepEqual(scopeObjectIds(rows, { path_prefix: 'C:/demo/' }, 1), { ids: null, overflow: 2, count: 2, chunks: 10 });
	assert.deepEqual(scopeObjectIds([doc('x', 'C:/demo/x', { chunks: null })], { path_prefix: 'C:/' }, 5).chunks, null, 'chunks only when every matching document was counted');
	const many = Array.from({ length: 2_340 }, (_, i) => doc(`d${i}`, `C:/demo/handbooks/${i}.md`));
	const big = scopeObjectIds(many, { path_prefix: 'C:/demo/handbooks/' }, 2_000);
	assert.equal(big.ids, null);
	assert.equal(big.overflow, 2_340);
});

test('matching 5,000 rows against every condition stays inside a keystroke (16 ms)', () => {
	const rows = Array.from({ length: 5_000 }, (_, i) => doc(`d${i}`, `C:/demo/f${i % 40}/doc_${i}.${i % 3 === 0 ? 'pdf' : 'md'}`, { chunks: i % 90, ingestedAt: `2026-10-0${1 + (i % 8)}T10:00:00Z`, tables: i % 5 }));
	const filter: IDocumentsFilter = { path_prefix: 'C:/demo/f1', file_types: ['md'], ingested_after: '2026-10-03T00:00:00Z', min_chunks: 2, max_chunks: 60, has_tables: true, has_first_chunk: true, path_contains: 'doc_1' };
	scopeObjectIds(rows, filter, 2_000);
	const started = performance.now();
	for (let i = 0; i < 5; i += 1) scopeObjectIds(rows, filter, 2_000);
	const each = (performance.now() - started) / 5;
	assert.ok(each <= 16 * 3, `matching took ${each.toFixed(1)} ms (budget 16 ms, asserted ≤ 3×)`);
});

// =============================================================================
// AVAILABILITY AND WORDS
// =============================================================================

test('conditions the store cannot answer are disabled with their sentence', () => {
	const rows = [doc('a', 'a.md')];
	assert.deepEqual(conditionAvailability('ingestedAfter', { caveats: ['extras_not_stored'], rows }), { enabled: false, reason: 'This store does not keep ingest times' });
	assert.deepEqual(conditionAvailability('ingestedBefore', { caveats: ['extras_not_stored'], rows }), { enabled: false, reason: 'This store does not keep ingest times' });
	assert.deepEqual(conditionAvailability('ingestedAfter', { caveats: [], rows }), { enabled: true, reason: null });
	assert.deepEqual(conditionAvailability('chunks', { caveats: [], rows: [doc('a', 'a', { chunks: null })] }), { enabled: false, reason: 'This store does not count chunks per document' });
	assert.deepEqual(conditionAvailability('hasTables', { caveats: [], rows: [doc('a', 'a', { tables: null })] }), { enabled: false, reason: 'This store does not count table chunks' });
	assert.deepEqual(conditionAvailability('chunks', { caveats: [], rows: [] }), { enabled: true, reason: null }, 'nothing loaded yet: offered');
	assert.deepEqual(conditionAvailability('folder', { caveats: ['extras_not_stored'], rows }), { enabled: true, reason: null });
});

test('the status line under the bar: store, partly here, or here over what is loaded', () => {
	assert.equal(scopeStatusText({ applied: 'server', ignored: [], count: 12, loaded: 12, total: 12, settled: true }), '12 documents match (store)');
	assert.equal(scopeStatusText({ applied: 'server', ignored: [], count: 1, loaded: 1, total: 1, settled: true }), '1 document matches (store)');
	assert.equal(scopeStatusText({ applied: 'server', ignored: [], count: 2_340, loaded: 500, total: 2_340, settled: false }), '2,340 documents match (store)');
	assert.equal(scopeStatusText({ applied: 'partial', ignored: ['ingested_after', 'ingested_before'], count: 12, loaded: 30, total: 30, settled: true }), '12 documents match (store; ingest dates filtered here)');
	assert.equal(scopeStatusText({ applied: 'partial', ignored: ['file_types', 'min_chunks'], count: 3, loaded: 9, total: 9, settled: true }), '3 documents match (store; file types and chunk counts filtered here)');
	assert.equal(scopeStatusText({ applied: 'none', ignored: ['path_prefix'], count: 12, loaded: 1_200, total: null, settled: false }), '12 of 1,200 loaded match (filtered here; the store cannot filter by these)');
	assert.equal(scopeStatusText({ applied: 'here', ignored: [], count: 12, loaded: 1_200, total: null, settled: true }), '12 of 1,200 loaded match (filtered here)');
});

test('the scope too large for the map, search and chat: the sentence, and those three toggles disabled with it', () => {
	assert.equal(tooLargeText(2_340, 2_000), 'Scope too large for the map, search and chat (2,340 documents; at most 2,000). Narrow the folder.');
	const big = { ...scopeOf({ path_prefix: 'C:/demo/' }), overflow: 2_340 };
	const av = scopeAvailability(big, 2_000);
	assert.deepEqual(av.documents, { enabled: true, reason: null });
	for (const target of ['map', 'search', 'chat'] as const) assert.deepEqual(av[target], { enabled: false, reason: tooLargeText(2_340, 2_000) }, target);
	const none = { ...scopeOf({ path_prefix: 'C:/nothing/' }), objectIds: [] as string[] };
	for (const target of ['map', 'search', 'chat'] as const) assert.deepEqual(scopeAvailability(none, 2_000)[target], { enabled: false, reason: 'No document matches these conditions, so the map, search and chat are not scoped.' }, target);
	const fine = { ...scopeOf({ path_prefix: 'C:/demo/' }), objectIds: ['a'] };
	for (const target of ['documents', 'map', 'search', 'chat'] as const) assert.deepEqual(scopeAvailability(fine, 2_000)[target], { enabled: true, reason: null }, target);
});

test("the stats strip's scope line counts documents against the store's figure and sums the chunks here", () => {
	const stats = readStats(fixture('stats_pgvector'));
	assert.equal(scopeStripText({ count: 12, chunks: 318, settled: true, loaded: 12 }, stats), 'Scope: 12 of 42 documents · 318 chunks (counted here)');
	assert.equal(scopeStripText({ count: 12, chunks: null, settled: true, loaded: 12 }, stats), 'Scope: 12 of 42 documents');
	assert.equal(scopeStripText({ count: 1, chunks: 4, settled: true, loaded: 1 }, null), 'Scope: 1 document · 4 chunks (counted here)');
	assert.equal(scopeStripText({ count: 2_340, chunks: 900, settled: false, loaded: 500 }, stats), 'Scope: 2,340 of 42 documents · 900 chunks in the 500 loaded (counted here)');
});

// =============================================================================
// RESOLVING THE SCOPE FROM THE DIRECTORY
// =============================================================================

test('a server-filtered listing: the scope is every listed document once the listing settles, null while it loads', () => {
	const server = readDocumentsPage(fixture('documents_filter_server'));
	const filter = { path_prefix: 'C:/demo/greenhouse/' };
	const loading = pagerBegin(pagerInit(), filter);
	assert.equal(resolveScope(scopeOf(filter), loading, 2_000).objectIds, null, 'unresolved while the first page is on its way');
	const done = pagerApplyPage(loading, server);
	assert.equal(done.filterApplied, 'server');
	const resolved = resolveScope(scopeOf(filter), done, 2_000);
	assert.deepEqual(
		resolved.objectIds,
		server.items.map((i) => i.objectId)
	);
	assert.equal(resolved.overflow, null);
	assert.equal(resolved.label, 'folder is under C:/demo/greenhouse/');
});

test("a partial answer: the store's rows are filtered here by the keys it skipped", () => {
	const filter: IDocumentsFilter = { path_prefix: 'C:/demo/handbooks/', ingested_after: '2026-10-01T00:00:00Z' };
	const done = pagerApplyPage(pagerBegin(pagerInit(), filter), readDocumentsPage(fixture('documents_filter_partial')));
	assert.deepEqual(done.filterIgnored, ['ingested_after']);
	assert.deepEqual(resolveScope(scopeOf(filter), done, 2_000).objectIds, [], 'the legacy row has no ingest time, so it cannot be shown to match');
});

test('a store that filters nothing (none, or an older node that ignores the filter): the loaded rows are matched here', () => {
	const filter: IDocumentsFilter = { path_prefix: 'C:/demo/handbooks/', file_types: ['md'] };
	const none = pagerApplyPage(pagerBegin(pagerInit(), filter), readDocumentsPage({ ...fixture('documents_filter_client'), next_cursor: null }));
	assert.equal(none.filterApplied, 'none');
	const falcon = none.rows.filter((r) => r.path === 'C:/demo/handbooks/falcon_handbook.md').map((r) => r.objectId);
	assert.equal(falcon.length, 1);
	assert.deepEqual(resolveScope(scopeOf(filter), none, 2_000).objectIds, falcon);
	const old = listed(readDocumentsPage(fixture('documents_page1')).items, filter);
	assert.equal(old.filterApplied, 'none', 'an answer without filter_applied came from a node that ignored the filter');
	assert.deepEqual(old.filterIgnored, ['path_prefix', 'file_types']);
	assert.deepEqual(resolveScope(scopeOf(filter), old, 2_000).objectIds, falcon);
});

test('the Documents toggle off: the directory lists everything and the scope is matched here over the loaded rows', () => {
	const rows = readDocumentsPage(fixture('documents_page1')).items;
	const dir = listed(rows, null);
	const scope = scopeOf({ path_prefix: 'C:/demo/greenhouse/' }, { documents: false });
	assert.deepEqual(resolveScope(scope, dir, 2_000).objectIds?.length, 2);
	assert.equal(dir.filterApplied, null);
});

test('the path box narrows the scope here, never through the store', () => {
	const filter: IDocumentsFilter = { path_prefix: 'C:/demo/greenhouse/', path_contains: 'TXT' };
	const done = pagerApplyPage(pagerBegin(pagerInit(), listingFilter(filter)), readDocumentsPage(fixture('documents_filter_server')));
	const resolved = resolveScope(scopeOf(filter), done, 2_000);
	assert.deepEqual(
		resolved.objectIds,
		done.rows.filter((r) => r.path.endsWith('.txt')).map((r) => r.objectId)
	);
});

test('above the cap: overflow with the count (from the store total when it said), no ids; resolution is stable', () => {
	const filter = { path_prefix: 'C:/demo/' };
	const rows = Array.from({ length: 500 }, (_, i) => doc(`d${i}`, `C:/demo/${i}.md`));
	const loading = { ...pagerApplyPage(pagerBegin(pagerInit(), filter), readDocumentsPage({ success: true, items: rows, next_cursor: 'c2', total: 2_340, counts_exact: true, distinct: true, sorted: true, caveats: [], filter_applied: 'server', filter_ignored: [] })) };
	assert.equal(loading.status, 'loading');
	const resolved = resolveScope(scopeOf(filter), loading, 2_000);
	assert.equal(resolved.overflow, 2_340, "known from the store's total before the listing ends");
	assert.equal(resolved.objectIds, null);
	assert.equal(resolveScope(resolved, loading, 2_000), resolved, 'resolving again returns the same object');
});

test('a scope is resolved only from the listing it asked for: a stale listing (the list not yet re-listed) resolves nothing', () => {
	const rows = readDocumentsPage(fixture('documents_page1')).items;
	const unfiltered = listed(rows, null);
	const scope = scopeOf({ path_prefix: 'C:/demo/greenhouse/' });
	const stale = resolveScope(scope, unfiltered, 2_000);
	assert.equal(stale.objectIds, null, 'the list is still the unfiltered one: wait for the filtered listing');
	assert.equal(stale.overflow, null);
	const greenhouse = listed(
		rows.filter((r) => r.path.startsWith('C:/demo/greenhouse/')),
		{ path_prefix: 'C:/demo/handbooks/' },
		{ filter_applied: 'server', filter_ignored: [] }
	);
	assert.equal(resolveScope(scope, greenhouse, 2_000).objectIds, null, 'a listing for other conditions resolves nothing');
	const off = resolveScope({ ...scope, applyTo: { ...scope.applyTo, documents: false } }, greenhouse, 2_000);
	assert.equal(off.objectIds, null, 'Documents off waits for the unfiltered listing');
	assert.equal(resolveScope({ ...scope, applyTo: { ...scope.applyTo, documents: false } }, unfiltered, 2_000).objectIds?.length, 2);
});

test('building scopes: no condition is no scope, the same conditions keep the scope, a chart or a saved filter sets its kinds', () => {
	assert.equal(scopeFromFilter({ conditions: [], text: 'falcon' }, null), null, 'the path box alone is not a scope');
	const first = scopeFromFilter({ conditions: [{ kind: 'folder', prefix: 'C:/demo/' }], text: '' }, null);
	assert.ok(first);
	assert.deepEqual(first.applyTo, { documents: true, map: true, search: true, chat: true });
	assert.equal(first.label, 'folder is under C:/demo/');
	const resolved = { ...first, objectIds: ['a'], applyTo: { ...first.applyTo, chat: false } };
	assert.equal(scopeFromFilter(filterOf(resolved, ''), resolved), resolved, 'nothing changed: the same scope');
	const typed = withText(resolved, 'orchid');
	assert.deepEqual(typed.filter, { path_prefix: 'C:/demo/', path_contains: 'orchid' });
	assert.equal(typed.objectIds, null, 'new conditions are unresolved');
	assert.equal(typed.applyTo.chat, false, 'the toggles are kept');
	assert.equal(withText(typed, 'orchid'), typed);
	const charted = scopeWith(typed, 'orchid', { min_chunks: 64, max_chunks: 127 });
	assert.deepEqual(charted?.filter, { path_prefix: 'C:/demo/', min_chunks: 64, max_chunks: 127, path_contains: 'orchid' });
	const folder = scopeWith(charted, 'orchid', { path_prefix: 'C:/demo/handbooks/' });
	assert.equal(folder?.filter.path_prefix, 'C:/demo/handbooks/', 'Scope to this folder replaces the folder');
	assert.deepEqual(scopeWith(null, '', { file_types: ['pdf'] })?.filter, { file_types: ['pdf'] }, 'a chart bar with no scope starts one');
});
