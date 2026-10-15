// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// LIVE CAPTURES: the app reads every answer the live drivers gave
// =============================================================================
//
// tests/fixtures/v1/live/<backend>/ holds real tool answers captured from the
// shipped templates in an engine against the live test databases, on a new
// collection and on a legacy-shaped one (nodes/test/vector_wire_fixtures.py;
// test_vector_wire_fixtures_full.py fails when they no longer match the
// tools). The other suites run on the hand-written provisional fixtures; this
// one runs the app's readers over the captures, so a field a driver really
// sends differently fails here.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { ExplorerToolError } from 'shared/explorer';
import { CAVEATS, TOOL_CODES } from '../src/contract/types';
import { readChunksPage, readDialect, readDocumentsPage, readRemoveResult, readStats, unwrapEnvelope } from '../src/vector/results';
import { caveatSentence, codeSentence, GENERIC_REFUSAL } from '../src/vector/wording';

const LIVE = path.resolve(__dirname, 'fixtures', 'v1', 'live');
/** The supported backends, by the folder their captures are in. */
const BACKENDS = ['pgvector', 'rocketride_vector', 'qdrant', 'chroma'];
/** The two collections every capture is taken on: '' (new) and '.legacy'. */
const KINDS = ['', '.legacy'];

type Answer = Record<string, any>;

/** One capture, parsed. */
function capture(backend: string, name: string): Answer {
	return JSON.parse(fs.readFileSync(path.join(LIVE, backend, `${name}.json`), 'utf8')) as Answer;
}

/** The capture names of a backend, without `.json`. */
function names(backend: string): string[] {
	return fs
		.readdirSync(path.join(LIVE, backend))
		.filter((file) => file.endsWith('.json'))
		.map((file) => file.slice(0, -'.json'.length))
		.sort();
}

/** The error unwrapEnvelope throws for a failure envelope. */
function refusal(tool: string, answer: Answer): ExplorerToolError {
	try {
		unwrapEnvelope(tool, answer);
	} catch (error) {
		assert.ok(error instanceof ExplorerToolError, `an ExplorerToolError, got ${String(error)}`);
		return error;
	}
	assert.fail(`${tool}: a failure envelope was read as a success`);
}

test('every supported backend has the captures the readers below use, on a new and a legacy collection', () => {
	for (const backend of BACKENDS) {
		const present = new Set(names(backend));
		for (const base of ['dialect', 'stats', 'stats.quick', 'documents', 'chunks', 'remove_document', 'sample', 'search']) {
			for (const kind of KINDS) assert.ok(present.has(`${base}${kind}`), `${backend}/${base}${kind}.json is captured`);
		}
	}
});

test('dialect: every capture reads as a vector store of its backend, and every caveat it names has a sentence', () => {
	for (const backend of BACKENDS) {
		for (const kind of KINDS) {
			const dialect = readDialect(unwrapEnvelope('dialect', capture(backend, `dialect${kind}`)));
			assert.ok(dialect, `${backend}${kind}: read as a vector store`);
			assert.equal(dialect.backend, backend === 'rocketride_vector' ? 'pgvector' : backend);
			assert.equal(dialect.dimension, 384);
			for (const caveat of dialect.caveats) {
				assert.ok((CAVEATS as readonly string[]).includes(caveat), `${backend}${kind}: caveat ${caveat} is in the contract`);
				assert.ok(caveatSentence(caveat), `${backend}${kind}: caveat ${caveat} has a sentence`);
			}
		}
	}
});

test('stats: full and quick read with figures, and the legacy collection counts its document without a first chunk', () => {
	for (const backend of BACKENDS) {
		for (const kind of KINDS) {
			for (const mode of ['stats', 'stats.quick']) {
				const stats = readStats(unwrapEnvelope('stats', capture(backend, `${mode}${kind}`)));
				assert.equal(stats.legacyOnly, false, `${backend}/${mode}${kind}: the extended answer`);
				assert.equal(stats.collectionExists, true);
				assert.ok((stats.chunks ?? 0) > 0, `${backend}/${mode}${kind}: chunks counted`);
				assert.equal(stats.dimension, 384);
				assert.equal(stats.metric, 'cosine');
				for (const caveat of stats.caveats) assert.ok(caveatSentence(caveat), `${backend}/${mode}${kind}: caveat ${caveat} has a sentence`);
			}
			const full = readStats(capture(backend, `stats${kind}`));
			if (kind === '.legacy' && full.withoutFirstChunk !== null) assert.equal(full.withoutFirstChunk, 1, `${backend}: the planted orphan`);
		}
	}
});

test('documents: every row of a first page reads, and a document without its first chunk appears only on the legacy collection', () => {
	for (const backend of BACKENDS) {
		for (const kind of KINDS) {
			const raw = capture(backend, `documents${kind}`);
			const page = readDocumentsPage(unwrapEnvelope('documents', raw));
			assert.equal(page.items.length, raw.items.length, `${backend}${kind}: no row dropped`);
			assert.ok(
				page.items.every((item) => item.objectId && item.path.startsWith('C:/demo/')),
				`${backend}${kind}: ids and paths`
			);
			// The captures hold a first page; an unsorted store lists its orphan at the end of the listing.
			const orphans = page.items.filter((item) => !item.has_first_chunk).length;
			if (kind === '') assert.equal(orphans, 0, `${backend}: a new collection has no document without its first chunk`);
			else assert.ok(orphans <= 1, `${backend}${kind}: at most the planted orphan`);
			if (kind === '.legacy' && page.sorted) assert.equal(orphans, 1, `${backend}${kind}: a sorted first page lists the planted orphan`);
		}
	}
});

test('chunks: pages read in chunk order and never carry a vector', () => {
	for (const backend of BACKENDS) {
		for (const kind of KINDS) {
			const page = readChunksPage(unwrapEnvelope('chunks', capture(backend, `chunks${kind}`)));
			assert.ok(page.items.length > 0, `${backend}${kind}: a page`);
			const ids = page.items.map((item) => item.chunkId);
			assert.deepEqual(
				ids,
				[...ids].sort((a, b) => a - b)
			);
			for (const item of page.items) {
				assert.ok(!('vector' in item.metadata) && !('embedding' in item.metadata), `${backend}${kind}: no vector in metadata`);
			}
		}
	}
});

test('remove_document: the rows the node removed are read as it reported them', () => {
	for (const backend of BACKENDS) {
		for (const kind of KINDS) {
			const raw = capture(backend, `remove_document${kind}`);
			const removed = readRemoveResult(unwrapEnvelope('remove_document', raw));
			assert.equal(removed.removed.length, raw.removed.length, `${backend}${kind}: every removed document`);
			assert.equal(removed.removedChunks, raw.removed_chunks ?? null);
		}
	}
});

test('refusals: every captured failure is a store error that keeps its documented code and has its own sentence', () => {
	let seen = 0;
	for (const backend of BACKENDS) {
		for (const name of names(backend)) {
			const answer = capture(backend, name);
			if (answer.success !== false) continue;
			seen += 1;
			const tool = name.split('.')[0];
			const error = refusal(tool, answer);
			assert.equal(error.kind, 'store', `${backend}/${name}`);
			assert.ok((TOOL_CODES as readonly string[]).includes(error.code ?? ''), `${backend}/${name}: ${error.code} is a contract code`);
			assert.notEqual(codeSentence(error.code), GENERIC_REFUSAL, `${backend}/${name}: ${error.code} has its own sentence`);
			const casePart = name.split('.')[1];
			if (casePart && casePart !== 'legacy') assert.equal(error.code, casePart.toUpperCase(), `${backend}/${name}: the capture is for ${casePart}`);
		}
	}
	assert.ok(seen >= BACKENDS.length * 4, `refusal captures were read (${seen})`);
});
