// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Self-test for browser/lane_vector_enrich.cjs (the enrichment lane, gate GE3)
 * and for the seeders its rows rely on, without a browser or an engine: the
 * planted facts of demo/gen_corpus.py (the keyword token, the 600-document
 * scope folder), gen_perf.py's check that a sample can carry every edge row,
 * the lane's own verdicts on hand-made answers, and the lane run against both
 * stand-in pages, where every step must FAIL.
 * Run: node --test scripts/acceptance/vector-explorer/selftest/*.test.cjs
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const ACC = path.join(__dirname, '..');

/** Run a Python snippet with the acceptance folders on its path; its JSON output. */
function python(code) {
	const res = spawnSync('python3', ['-c', `import json, sys\nsys.path[:0] = ${JSON.stringify([path.join(ACC, 'demo'), path.join(ACC, 'browser')])}\n${code}`], { encoding: 'utf8', timeout: 120000 });
	if (res.status !== 0) throw new Error(`python3 failed (${res.status}):\n${res.stdout}${res.stderr}`);
	return JSON.parse(res.stdout);
}

/** Write the corpus with gen_corpus.py into a fresh folder; { dir, files: relative paths, status }. */
function writeCorpus(...args) {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vx-enrich-corpus-'));
	const res = spawnSync('python3', [path.join(ACC, 'demo', 'gen_corpus.py'), dir, ...args], { encoding: 'utf8', timeout: 120000 });
	const files = [];
	const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : files.push(path.relative(dir, path.join(d, e.name)).split(path.sep).join('/'))));
	if (fs.existsSync(dir)) walk(dir);
	return { dir, files: files.sort(), status: res.status, out: `${res.stdout}${res.stderr}` };
}

// ---------------------------------------------------------------------------
// The seeders: the demo corpus's planted facts and the perf fixture's edge sample
// ---------------------------------------------------------------------------

test('gen_corpus: the keyword token is planted once, as a whole word, in a document the live suites upload', () => {
	const facts = python(`
import gen_corpus as g
corpus = g.build_corpus()
import re
hits = sorted(p for p, t in corpus.items() if g.KEYWORD_TOKEN in t)
whole = sorted(p for p, t in corpus.items() if re.search(r'(?<![A-Za-z0-9])' + g.KEYWORD_TOKEN + r'(?![A-Za-z0-9])', t))
print(json.dumps({'token': g.KEYWORD_TOKEN, 'file': g.KEYWORD_FILE, 'hits': hits, 'whole': whole, 'count': sum(t.count(g.KEYWORD_TOKEN) for t in corpus.values()), 'documents': len(corpus)}))
`);
	assert.strictEqual(facts.token, 'KX4471');
	assert.deepStrictEqual(facts.hits, [facts.file]);
	assert.deepStrictEqual(facts.whole, [facts.file]);
	assert.strictEqual(facts.count, 1);
	assert.strictEqual(facts.documents, 40, 'the default corpus keeps its forty documents');
	// The toolpath suite and the wire captures upload a fixed subset: the token must be in it, so
	// keyword search is checked on every backend's live collection too.
	const toolpath = fs.readFileSync(path.join(ACC, '..', '..', '..', 'nodes', 'test', 'test_vector_toolpath_full.py'), 'utf8');
	assert.match(toolpath, new RegExp(`'${facts.file.replace(/[.]/g, '\\.')}'`), `${facts.file} is one of the toolpath suite's CORPUS_DOCS`);
});

test("gen_corpus: every greenhouse document names the orchid house, so whichever greenhouse cluster a sample draws is labelled 'orchid'", () => {
	// The node labels a cluster with the top TF-IDF terms of up to 50 of its chunks: the word must be
	// frequent in every greenhouse document, not only in orchid_notes.txt, for any split of the folder.
	const counts = python(`
import re, gen_corpus as g
corpus = g.build_corpus()
print(json.dumps({p: len(re.findall(r'\\borchid\\b', t)) for p, t in corpus.items() if p.startswith('greenhouse/')}))
`);
	assert.strictEqual(Object.keys(counts).length, 6);
	for (const [file, n] of Object.entries(counts)) assert.ok(n >= 2, `${file} names the orchid ${n} times`);
	const elsewhere = python(`
import re, gen_corpus as g
print(json.dumps(sorted(p for p, t in g.build_corpus().items() if not p.startswith('greenhouse/') and re.search(r'\\borchid', t))))
`);
	assert.deepStrictEqual(elsewhere, [], 'no other folder mentions orchids, so the word sets that cluster apart');
});

test('gen_corpus --pad 600: six hundred one-chunk documents in their own folder, written the same way every run', () => {
	const plain = writeCorpus();
	const padded = writeCorpus('--pad', '600');
	try {
		assert.strictEqual(plain.status, 0, plain.out);
		assert.strictEqual(padded.status, 0, padded.out);
		assert.strictEqual(plain.files.length, 40);
		const pad = padded.files.filter((f) => f.startsWith('pad/'));
		assert.strictEqual(pad.length, 600);
		assert.deepStrictEqual(
			padded.files.filter((f) => !f.startsWith('pad/')),
			plain.files,
			'the forty documents are unchanged'
		);
		for (const f of pad) {
			assert.match(f, /^pad\/[a-z0-9_]+\.txt$/);
			const text = fs.readFileSync(path.join(padded.dir, f), 'utf8');
			// One chunk each, far below the calibrated chunk length.
			assert.ok(text.length > 40 && text.length < 400, `${f}: ${text.length} characters`);
		}
		assert.strictEqual(new Set(pad.map((f) => fs.readFileSync(path.join(padded.dir, f), 'utf8'))).size, 600, 'every padding document has its own text');
		// --check compares the padded corpus, and finds the padding missing from a plain copy.
		assert.strictEqual(spawnSync('python3', [path.join(ACC, 'demo', 'gen_corpus.py'), padded.dir, '--pad', '600', '--check'], { encoding: 'utf8' }).status, 0);
		assert.strictEqual(spawnSync('python3', [path.join(ACC, 'demo', 'gen_corpus.py'), plain.dir, '--pad', '600', '--check'], { encoding: 'utf8' }).status, 1);
		// A bad count is refused.
		assert.notStrictEqual(spawnSync('python3', [path.join(ACC, 'demo', 'gen_corpus.py'), plain.dir, '--pad', '-3'], { encoding: 'utf8' }).status, 0);
	} finally {
		fs.rmSync(plain.dir, { recursive: true, force: true });
		fs.rmSync(padded.dir, { recursive: true, force: true });
	}
});

test('gen_corpus: the padding folder is the one the lane scopes to, and its upload names are the seeder prefix', () => {
	const facts = python(`
import gen_corpus as g
pad = g.pad_documents(600)
print(json.dumps({'folder': g.PAD_FOLDER, 'names': g.pad_upload_names(pad)[:2], 'n': len(pad)}))
`);
	assert.strictEqual(facts.folder, 'pad');
	assert.strictEqual(facts.n, 600);
	assert.deepStrictEqual(facts.names, ['C:/demo/pad/scope_note_0001.txt', 'C:/demo/pad/scope_note_0002.txt']);
	const seed = fs.readFileSync(path.join(ACC, 'demo', 'seed_demo.py'), 'utf8');
	assert.strictEqual(/^DEMO_PREFIX = '([^']*)'/m.exec(seed)[1], 'C:/demo/', "the padding is uploaded under seed_demo.py's prefix");
});

test("gen_perf: a sample can carry the lane's edge rows only with n points and enough kNN neighbours per point", () => {
	const r = python(`
import gen_perf as g
def answer(n, degree, **extra):
    offsets = [i * degree for i in range(n + 1)]
    a = {'success': True, 'n': n, 'knn': {'k': degree, 'offsets_row': offsets, 'cols': [0] * (n * degree), 'sims': [0.5] * (n * degree)}}
    a.update(extra)
    return a
short = answer(6, 5)
short['knn']['offsets_row'] = [0, 5, 10, 14, 19, 24, 29]
short['knn']['cols'] = [0] * 29
print(json.dumps({
    'rows': list(g.EDGE_ROWS),
    'n': g.EDGE_SAMPLE_N,
    'need': g.edges_needed(),
    'sound': g.edge_sample_problems(answer(6, 15), n=6),
    'small': g.edge_sample_problems(answer(5, 15), n=6),
    'few': g.edge_sample_problems(answer(6, 4), n=6),
    'short': g.edge_sample_problems(short, n=6),
    'none': g.edge_sample_problems({'success': True, 'n': 6}, n=6),
    'refused': g.edge_sample_problems({'success': False, 'code': 'BUSY'}, n=6),
    'tree_only': g.edges_needed(['none', 'tree']),
}))
`);
	const perf = require('../browser/lane_vector_perf.cjs');
	assert.deepStrictEqual(r.rows, perf.EDGE_MODES, "gen_perf.py's edge rows are the lane's");
	assert.strictEqual(r.n, perf.GATE.n);
	assert.strictEqual(r.need, 5);
	assert.deepStrictEqual(r.sound, []);
	assert.strictEqual(r.tree_only, 1);
	for (const key of ['small', 'few', 'short', 'none', 'refused']) assert.ok(r[key].length > 0, `${key}: ${JSON.stringify(r[key])}`);
	assert.match(r.few.join(' '), /fewer than 5 kNN neighbours/);
});
