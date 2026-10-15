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

// ---------------------------------------------------------------------------
// The lane on the stand-in pages: every step runs and none passes
// ---------------------------------------------------------------------------

const { runWithStandIn } = require('./stand_in.cjs');
const lane = require('../browser/lane_vector_enrich.cjs');
const E = require('../env.cjs');

// GE3's enrichment steps (ENRICHED_SPEC 4.1), each of which the lane must run on every backend.
const GE3 = [/clusters \(P0-1\)/, /Minimum size 2/, /Ask about these/, /edges \(P0-3\)/, /colour by ingest date \(P1-3\)/, /isolate \(P1-4\)/, /text \(P1-6\)/, /recommend \(P1-1\)/, /Best score/, /matrix \(P1-2\)/, /export \(P0-6\)/, /map PNG/, /views \(P1-5\)/, /duplicates queue \(P0-4\)/, /outliers \(P1-8\)/, /charts \(P0-7\)/, /scope \(P0-2\)/, /Keyword finds KX4471/, /threshold slider/, /Compare/, /55 %/, /duplicates removal/, /outlier removal/, /ingest summary \(P1-9\)/, /restore/, /sign-out/, /privacy \(B4\)/];
// Steps that belong to some backends only.
const ONLY = { qdrant: [/scope of 600/, /listing \(the scope card\)/], chroma: [/scope of 600/, /listing \(the scope card\)/], postgres: [/health \(P1-7\)/] };

const runs = {};
const standIn = (fixture, variant) => (runs[`${fixture}:${variant}`] ||= runWithStandIn('lane_vector_enrich.cjs', [fixture], 'lane_vector_enrich.json', variant));

// Every backend on the empty page; the backends with steps of their own also on the page full of silent elements.
for (const fixture of ['qdrant', 'postgres', 'chroma', 'rocketride_vector']) {
	for (const variant of fixture === 'qdrant' || fixture === 'postgres' ? ['empty', 'visible'] : ['empty']) {
		test(`lane_vector_enrich: on ${fixture}, every step runs and fails on the ${variant} stand-in page`, () => {
			const { data, stdout } = standIn(fixture, variant);
			for (const name of [...GE3, ...(ONLY[fixture] || [])])
				assert.ok(
					data.some((r) => name.test(r.name)),
					`no step for ${name}:\n${stdout}`
				);
			for (const [other, names] of Object.entries(ONLY)) {
				if (other === fixture) continue;
				for (const name of names.filter((n) => !(ONLY[fixture] || []).some((m) => String(m) === String(n)))) assert.ok(!data.some((r) => name.test(r.name)), `${fixture} runs ${name}, a step of ${other} only`);
			}
			assert.strictEqual(data.length, lane.stepsFor(fixture).length, `the steps run are not the planned ones:\n${data.map((r) => r.name).join('\n')}`);
			const passed = data.filter((r) => r.status === 'PASS');
			assert.deepStrictEqual(passed, [], `steps passed without observing anything: ${JSON.stringify(passed)}`);
		});
	}
}

test('lane_vector_enrich: exits non-zero when a step failed', () => {
	assert.notStrictEqual(standIn('qdrant', 'empty').status, 0);
});

test('lane_vector_enrich: run by vector-ui:e2e-live it covers the named backends, and refuses another browser', () => {
	assert.deepStrictEqual(lane.laneArgs(['http://h', '/tmp/o', 'chrome', 'qdrant,chroma'], {}).fixtures, ['qdrant', 'chroma']);
	assert.deepStrictEqual(lane.laneArgs(['http://h', '/tmp/o', 'chrome'], {}).fixtures, lane.BACKENDS);
	assert.deepStrictEqual(lane.laneArgs(['http://h', '/tmp/o', 'chrome'], { VECTOR_UI_E2E_BACKENDS: 'postgres' }).fixtures, ['postgres']);
	assert.deepStrictEqual(lane.laneArgs(['http://h', '/tmp/o', 'postgres'], {}), { base: 'http://h', out: '/tmp/o', browser: null, fixtures: ['postgres'] });
	assert.deepStrictEqual(lane.laneArgs([], {}).fixtures, ['qdrant']);
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vx-enrich-e2e-'));
	try {
		const res = spawnSync(process.execPath, [path.join(ACC, 'browser', 'lane_vector_enrich.cjs'), 'http://127.0.0.1:9', dir, 'webkit', 'qdrant'], { encoding: 'utf8', env: { ...process.env, CLIENT_TS_DIR: path.join(dir, 'none') } });
		assert.notStrictEqual(res.status, 0);
		const rows = JSON.parse(fs.readFileSync(path.join(dir, 'lane_vector_enrich.json'), 'utf8'));
		assert.deepStrictEqual(
			rows.map((r) => [r.browser, r.backend, r.status]),
			[['webkit', 'qdrant', 'FAIL']]
		);
		assert.match(rows[0].detail, /Google Chrome only/);
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test('the lane writes lane_vector_enrich.json into its output folder (the file vector-ui:e2e-live reads)', () => {
	const source = fs.readFileSync(path.join(ACC, 'browser', 'lane_vector_enrich.cjs'), 'utf8');
	assert.ok(source.includes("path.join(out, 'lane_vector_enrich.json')"));
});

test("the lane's planted facts and its own cards are the generator's", () => {
	const facts = python(`
import gen_corpus as g
print(json.dumps({'token': g.KEYWORD_TOKEN, 'file': g.KEYWORD_FILE, 'pad': g.DEMO_PREFIX + g.PAD_FOLDER + '/', 'falcon': g.NEAR_DUPLICATES[0][0],
    'scope': {k: {'name': v[0], 'projectId': v[1]} for k, v in g.SCOPE_CARDS.items()}, 'legacy': {'name': g.LEGACY_CARD[0], 'projectId': g.LEGACY_CARD[1]},
    'collection': g.SCOPE_COLLECTION, 'table': g.LEGACY_TABLE}))
`);
	assert.deepStrictEqual(lane.SCOPE_FIXTURES, facts.scope);
	assert.deepStrictEqual(lane.LEGACY_FIXTURE, facts.legacy);
	assert.strictEqual(facts.table, 'vx_legacy_docs');
	assert.notStrictEqual(facts.collection, 'vx_demo_docs', 'the padding never goes into the demo collection');
	// The cards' project ids are their own: no fixture of env.cjs and not the perf card's.
	const ids = [...Object.values(facts.scope), facts.legacy].map((c) => c.projectId);
	const taken = [...Object.values(E.FIXTURES).map((f) => f.projectId), require('../browser/lane_vector_perf.cjs').PERF_PROJECT_ID];
	assert.deepStrictEqual(
		ids.filter((id) => taken.includes(id)),
		[]
	);
	assert.strictEqual(new Set(ids).size, ids.length);
	assert.strictEqual(lane.CORPUS.keywordToken, facts.token);
	assert.strictEqual(lane.CORPUS.keywordFile, facts.file);
	assert.strictEqual(lane.CORPUS.padFolder, facts.pad);
	assert.strictEqual(lane.CORPUS.falconFile, facts.falcon);
	assert.strictEqual(lane.CORPUS.scopeFolder, 'C:/demo/handbooks/');
});

// ---------------------------------------------------------------------------
// The lane's verdicts on hand-made answers: a sound case passes, each broken one fails
// ---------------------------------------------------------------------------

const D = 'C:/demo/';
const DOCS = [
	{ objectId: 'o-falcon', path: `${D}handbooks/falcon_handbook.md` },
	{ objectId: 'o-rev2', path: `${D}handbooks/falcon_handbook_rev2.md` },
	{ objectId: 'o-orchid', path: `${D}greenhouse/orchid_notes.txt` },
	{ objectId: 'o-tomato', path: `${D}greenhouse/tomato_trials.md` },
	{ objectId: 'o-manual', path: `${D}manuals/long_manual.md` },
	{ objectId: 'o-ocr', path: `${D}scans/ocr_scan_0417.txt` },
	{ objectId: 'o-kestrel', path: `${D}field/kestrel_field_guide.md` },
];
// 20 points: the manual (6, group 0), the greenhouse (5, group 1), the handbooks (5, group 2), the kestrel (2, group 3), the OCR junk (2, noise).
const DOC_OF = [4, 4, 4, 4, 4, 4, 2, 2, 2, 3, 3, 0, 0, 0, 1, 1, 6, 6, 5, 5];
const LABELS = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, -1, -1];
/** A chain within each group (each point linked to the next of its group), one edge each way. */
function chainKnn(labels) {
	const offsets = [0];
	const cols = [];
	labels.forEach((label, i) => {
		const next = labels.findIndex((l, j) => j > i && l === label && label >= 0);
		const prev = labels.slice(0, i).lastIndexOf(label);
		if (label >= 0 && prev >= 0) cols.push(prev);
		if (next >= 0) cols.push(next);
		offsets.push(cols.length);
	});
	return { k: 2, offsets_row: offsets, cols, sims: cols.map(() => 0.9) };
}
const sampleOf = (extra = {}) => ({
	success: true,
	n: 20,
	docs: DOCS.map((d, i) => ({ i, ...d })),
	points: { doc: DOC_OF.slice(), chunk: DOC_OF.map((_, i) => i), x: [], y: [], snip: DOC_OF.map((d) => (d === 0 ? 'Drinking water comes from the spring' : 'text')) },
	knn: chainKnn(LABELS),
	clusters: { method: 'knn-components', count: 4, noise: 2, labels: LABELS.slice(), sizes: [6, 5, 5, 2], keywords: [['procedure', 'pump'], ['orchid', 'house'], ['station', 'falcon'], []], labelled: 3 },
	outliers: [18, 19],
	duplicates: [],
	...extra,
});
const CLUSTER_INPUT = { n: 1000, cluster: { method: 'knn-components', labels: true } };
const ROWS = [
	{ size: 6, documents: 1 },
	{ size: 5, documents: 2 },
	{ size: 5, documents: 2 },
];

test('clustersVerdict: asked for clusters, 3 groups of 5 or more, orchid greenhouse, rows summing to n, Colour by Cluster', () => {
	const sound = { input: CLUSTER_INPUT, sample: sampleOf(), rows: ROWS, noise: 4, colourOffered: true, colourAfter: 'cluster' };
	assert.strictEqual(lane.clustersVerdict(sound), true);
	const broken = {
		'not asked': { input: { n: 1000 } },
		'no clusters': { sample: sampleOf({ clusters: undefined }) },
		'two groups': { sample: sampleOf({ clusters: { ...sampleOf().clusters, sizes: [6, 5, 4, 2] } }) },
		'no orchid': { sample: sampleOf({ clusters: { ...sampleOf().clusters, keywords: [['procedure'], ['tomato', 'house'], ['station'], []] } }) },
		'a row missing': { rows: ROWS.slice(0, 2) },
		'rows out of order': { rows: [ROWS[1], ROWS[0], ROWS[2]] },
		'noise miscounted': { noise: 2 },
		'Cluster not offered': { colourOffered: false },
		'Cluster not applied': { colourAfter: 'document' },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.clustersVerdict({ ...sound, ...change }), true, what);
});

test('minSizeVerdict: the rows follow the node groups at 5 and at 2, with no sample request', () => {
	const sample = sampleOf();
	assert.strictEqual(lane.minSizeVerdict({ sample, rows5: 3, rows2: 4, samplesSent: 0 }), true);
	assert.match(lane.minSizeVerdict({ sample, rows5: 3, rows2: 4, samplesSent: 1 }), /sent 1 sample/);
	assert.match(lane.minSizeVerdict({ sample, rows5: 3, rows2: 3, samplesSent: 0 }), /minimum size 2/);
	assert.match(lane.minSizeVerdict({ sample, rows5: 4, rows2: 4, samplesSent: 0 }), /minimum size 5/);
	assert.notStrictEqual(lane.minSizeVerdict({ sample: sampleOf({ clusters: undefined }), rows5: 0, rows2: 0, samplesSent: 0 }), true);
	assert.deepStrictEqual(lane.foldClusters(sample, 5), {
		rows: [
			{ cluster: 0, size: 6 },
			{ cluster: 1, size: 5 },
			{ cluster: 2, size: 5 },
		],
		noise: 4,
		n: 20,
	});
	assert.deepStrictEqual([...lane.clusterDocuments(sample, 1)].sort(), ['o-orchid', 'o-tomato']);
});

test("edgesVerdict: the tree is n minus the components, neighbours at most 5n, hover thickens, Expand adds the point's kNN edges", () => {
	const sample = sampleOf();
	// Components: 4 chains plus 2 isolated noise points.
	assert.strictEqual(lane.knnComponents(sample.knn, 20), 6);
	assert.strictEqual(lane.knnDegree(sample.knn, 1), 2);
	const sound = { sample, tree: 14, neighbours5: 30, hovered: 2, selected: 1, expanded: 2 };
	assert.strictEqual(lane.edgesVerdict(sound), true);
	for (const [what, change] of Object.entries({ 'tree count': { tree: 19 }, 'no neighbour edges': { neighbours5: 0 }, 'too many': { neighbours5: 101 }, 'no hover': { hovered: null }, 'no selection': { selected: null }, 'expand count': { expanded: 5 }, 'no graph': { sample: sampleOf({ knn: undefined }) } })) assert.notStrictEqual(lane.edgesVerdict({ ...sound, ...change }), true, what);
	// A point with no neighbour (noise) cannot be expanded.
	assert.notStrictEqual(lane.edgesVerdict({ ...sound, selected: 18, expanded: 0 }), true);
});

test('rampVerdict: the dated ramp names the first and last ingest day of the sampled documents', () => {
	const items = [{ ingestedAt: '2026-10-14T09:00:00Z' }, { ingestedAt: '2026-10-15T23:59:00Z' }, { ingestedAt: null }];
	const label = 'Colour ramp from oldest (2026-10-14) to newest (2026-10-15)';
	assert.strictEqual(lane.rampVerdict({ label, colourAfter: 'ingest-date', items }), true);
	assert.notStrictEqual(lane.rampVerdict({ label, colourAfter: 'document', items }), true);
	assert.notStrictEqual(lane.rampVerdict({ label: 'Colour ramp from oldest (2026-10-13) to newest (2026-10-15)', colourAfter: 'ingest-date', items }), true);
	assert.notStrictEqual(lane.rampVerdict({ label: null, colourAfter: 'ingest-date', items }), true);
	assert.match(lane.rampVerdict({ label, colourAfter: 'ingest-date', items: [{ ingestedAt: null }] }), /ingest time/);
});

test('isolateVerdict: shown points follow the selection, the table, Expand and Show all', () => {
	const sound = { n: 1000, selection: 40, isolated: { shown: 40, flag: '1' }, tableRows: 40, expanded: 95, all: { shown: 1000, flag: '0' } };
	assert.strictEqual(lane.isolateVerdict(sound), true);
	for (const [what, change] of Object.entries({ 'nothing selected': { selection: 0 }, 'everything selected': { selection: 1000 }, 'not isolated': { isolated: { shown: 1000, flag: '0' } }, 'table rows': { tableRows: 1000 }, 'expand did nothing': { expanded: 40 }, 'show all short': { all: { shown: 999, flag: '0' } }, 'still isolated': { all: { shown: 1000, flag: '1' } } })) assert.notStrictEqual(lane.isolateVerdict({ ...sound, ...change }), true, what);
});

test("chunkTextVerdict: 'water' is marked and the full text was fetched once for the key", () => {
	const key = ['o-falcon', 4];
	const call = { object_id: 'o-falcon', after_chunk: 3, limit: 1 };
	assert.strictEqual(lane.chunkTextVerdict({ marks: ['Water', 'spring'], calls: [call], key }), true);
	assert.notStrictEqual(lane.chunkTextVerdict({ marks: ['spring'], calls: [call], key }), true);
	assert.notStrictEqual(lane.chunkTextVerdict({ marks: ['water'], calls: [call, call], key }), true);
	assert.notStrictEqual(lane.chunkTextVerdict({ marks: ['water'], calls: [{ ...call, after_chunk: 4 }], key }), true);
});

test('recommendVerdict and bestScoreVerdict: examples sent, excluded, no greenhouse, falcon first; best_score native only where flagged', () => {
	const positive = ['o-falcon', 0];
	const negative = ['o-orchid', 6];
	const input = { positive: [positive], negative: [negative], k: 12, strategy: 'average_vector' };
	const items = [
		{ key: ['o-rev2', 0], path: DOCS[1].path },
		{ key: ['o-kestrel', 2], path: DOCS[6].path },
	];
	assert.strictEqual(lane.recommendVerdict({ input, answer: { success: true, items }, positive, negative }), true);
	const broken = {
		'positive missing': { input: { ...input, positive: [] } },
		'negative missing': { input: { ...input, negative: [] } },
		refused: { answer: { success: false, code: 'NOT_FOUND' } },
		'an example back': { answer: { success: true, items: [{ key: positive, path: DOCS[0].path }, ...items] } },
		'a greenhouse chunk': { answer: { success: true, items: [...items, { key: ['o-tomato', 1], path: DOCS[3].path }] } },
		'manual first': { answer: { success: true, items: [{ key: ['o-manual', 1], path: DOCS[4].path }, ...items] } },
		'nothing found': { answer: { success: true, items: [] } },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.recommendVerdict({ input, answer: { success: true, items }, positive, negative, ...change }), true, what);
	assert.strictEqual(lane.bestScoreVerdict({ capability: true, answer: { success: true, native: true, strategy_used: 'best_score', items } }), true);
	assert.notStrictEqual(lane.bestScoreVerdict({ capability: true, answer: { success: true, native: false, strategy_used: 'best_score' } }), true);
	assert.strictEqual(lane.bestScoreVerdict({ capability: false, answer: { success: false, code: 'UNSUPPORTED' } }), true);
	assert.notStrictEqual(lane.bestScoreVerdict({ capability: false, answer: { success: true, native: false } }), true);
});

test('matrixVerdict: the selected keys, no indices, a symmetric unit-diagonal matrix, same-document pairs above 0.5', () => {
	const keys = [
		['o-falcon', 0],
		['o-falcon', 1],
		['o-rev2', 0],
	];
	const allowed = new Set(['o-falcon#0', 'o-falcon#1', 'o-rev2#0', 'o-rev2#1']);
	const matrix = [
		[1, 0.8, 0.99],
		[0.8, 1, 0.7],
		[0.99, 0.7, 1],
	];
	const answer = { success: true, n: 3, keys, metric: 'cosine', matrix, source: 'cache' };
	const sound = { input: { keys }, answer, selected: 3, allowed };
	assert.strictEqual(lane.matrixVerdict(sound), true);
	const broken = {
		indices: { input: { keys, indices: [0, 1, 2] } },
		'a sample id': { input: { keys, sample_id: 's-7-a' } },
		'no keys': { input: { indices: [0, 1, 2] } },
		'a key twice': { input: { keys: [...keys, keys[0]] } },
		'fewer than selected': { selected: 4 },
		'a key not selected': { allowed: new Set(['o-falcon#0', 'o-falcon#1']) },
		'not square': { answer: { ...answer, matrix: matrix.slice(0, 2) } },
		'not symmetric': {
			answer: {
				...answer,
				matrix: [
					[1, 0.8, 0.99],
					[0.2, 1, 0.7],
					[0.99, 0.7, 1],
				],
			},
		},
		diagonal: {
			answer: {
				...answer,
				matrix: [
					[0.9, 0.8, 0.99],
					[0.8, 1, 0.7],
					[0.99, 0.7, 1],
				],
			},
		},
		'same document dissimilar': {
			answer: {
				...answer,
				matrix: [
					[1, 0.1, 0.99],
					[0.1, 1, 0.7],
					[0.99, 0.7, 1],
				],
			},
		},
		refused: { answer: { success: false, code: 'NOT_FOUND' } },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.matrixVerdict({ ...sound, ...change }), true, what);
});

test("selectionCsvVerdict and exportNameVerdict: one row per selected point of the sample, no vector or secret, the app's file name", () => {
	const sample = sampleOf();
	const sampleKeys = Array.from({ length: 20 }, (_, i) => lane.keyOf(sample, i));
	const header = 'objectId,chunkId,path,chunk_index,length,density,cluster,cluster_label,query_similarity,is_duplicate,is_outlier,x,y,z,snippet';
	const row = (i) => `${sampleKeys[i][0]},${sampleKeys[i][1]},${lane.pathOf(sample, i)},${i},800,0.61,0,procedure · pump,,false,false,0.12,-0.5,,"a ""quoted"", snippet"`;
	const csv = [header, row(0), row(1), row(2)].join('\r\n') + '\r\n';
	const secrets = { 'the API key': 'local-acceptance-key' };
	assert.strictEqual(lane.selectionCsvVerdict({ csv, selection: 3, sampleKeys, dim: 8, secrets }), true);
	assert.match(lane.selectionCsvVerdict({ csv, selection: 4, sampleKeys, dim: 8, secrets }), /3 rows for 4/);
	assert.match(lane.selectionCsvVerdict({ csv: [header, row(0), row(0)].join('\r\n'), selection: 2, sampleKeys, dim: 8, secrets }), /twice/);
	assert.match(lane.selectionCsvVerdict({ csv: [header, row(0).replace('o-manual', 'o-gone')].join('\r\n'), selection: 1, sampleKeys, dim: 8, secrets }), /not points of the sample/);
	assert.match(lane.selectionCsvVerdict({ csv: csv.replace('procedure · pump', 'local-acceptance-key'), selection: 3, sampleKeys, dim: 8, secrets }), /API key/);
	assert.match(lane.selectionCsvVerdict({ csv: csv.replace('"a ""quoted"", snippet"', '"[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]"'), selection: 3, sampleKeys, dim: 8, secrets }), /float/);
	assert.match(lane.selectionCsvVerdict({ csv: 'path\r\nx\r\n', selection: 1, sampleKeys, dim: 8, secrets }), /objectId column/);
	assert.strictEqual(lane.exportNameVerdict('vector-explorer_vx_demo_docs_selection_20261015-2310.csv', 'vx_demo_docs', 'selection', 'csv'), true);
	assert.notStrictEqual(lane.exportNameVerdict('export.csv', 'vx_demo_docs', 'selection', 'csv'), true);
	assert.notStrictEqual(lane.exportNameVerdict('vector-explorer_other_selection_20261015-2310.csv', 'vx_demo_docs', 'selection', 'csv'), true);
});

/** A PNG of w x h RGBA pixels from a pixel function (filter 0 rows), as a canvas writes it. */
function png(w, h, pixel, extraBytes = 0) {
	const crcTable = Array.from({ length: 256 }, (_, n) => {
		let c = n;
		for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
		return c >>> 0;
	});
	const crc = (buf) => {
		let c = 0xffffffff;
		for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
		return (c ^ 0xffffffff) >>> 0;
	};
	const chunk = (type, data) => {
		const len = Buffer.alloc(4);
		len.writeUInt32BE(data.length);
		const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
		const sum = Buffer.alloc(4);
		sum.writeUInt32BE(crc(body));
		return Buffer.concat([len, body, sum]);
	};
	const ihdr = Buffer.alloc(13);
	ihdr.writeUInt32BE(w, 0);
	ihdr.writeUInt32BE(h, 4);
	ihdr[8] = 8;
	ihdr[9] = 6;
	const raw = Buffer.alloc(h * (w * 4 + 1));
	for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) Buffer.from(pixel(x, y)).copy(raw, y * (w * 4 + 1) + 1 + x * 4);
	const text = extraBytes ? [chunk('tEXt', Buffer.concat([Buffer.from('Comment\0'), require('crypto').randomBytes(extraBytes)]))] : [];
	return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), ...text, chunk('IDAT', require('zlib').deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

test('pngInfo and pngVerdict: over 10 KB, drawn pixels of more than one colour, named after the collection', () => {
	const drawn = png(96, 64, (x, y) => ((x * 7 + y * 3) % 11 === 0 ? [200, 40, 40, 255] : [250, 250, 250, 255]), 12000);
	const info = lane.pngInfo(drawn);
	assert.deepStrictEqual([info.width, info.height, info.colourType], [96, 64, 6]);
	assert.strictEqual(info.opaque, info.sampled);
	assert.ok(info.distinct >= 2);
	const name = 'vector-explorer_vx_demo_docs_map_20261015-2310.png';
	assert.strictEqual(lane.pngVerdict({ name, bytes: drawn, collection: 'vx_demo_docs' }), true);
	assert.match(lane.pngVerdict({ name, bytes: png(96, 64, () => [0, 0, 0, 0], 12000), collection: 'vx_demo_docs' }), /transparent/);
	assert.match(lane.pngVerdict({ name, bytes: png(96, 64, () => [250, 250, 250, 255], 12000), collection: 'vx_demo_docs' }), /1 colour/);
	assert.match(lane.pngVerdict({ name, bytes: png(96, 64, (x) => [x, 0, 0, 255]), collection: 'vx_demo_docs' }), /over 10 KB/);
	assert.match(lane.pngVerdict({ name: 'map.png', bytes: drawn, collection: 'vx_demo_docs' }), /named/);
	assert.match(lane.pngVerdict({ name, bytes: Buffer.alloc(20000, 1), collection: 'vx_demo_docs' }), /not an 8-bit/);
	// Rows written with the Sub, Up, Average and Paeth filters decode to the same pixels.
	for (const filter of [1, 2, 3, 4]) {
		const plain = png(4, 3, (x, y) => [x * 40, y * 60, 90, 255]);
		const ihdrEnd = 8 + 25;
		const idatLen = plain.readUInt32BE(ihdrEnd);
		const raw = Buffer.from(require('zlib').inflateSync(plain.subarray(ihdrEnd + 8, ihdrEnd + 8 + idatLen)));
		const stride = 16;
		const px = (y) => raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
		const orig = [0, 1, 2].map((y) => Buffer.from(px(y)));
		for (let y = 0; y < 3; y += 1) {
			raw[y * (stride + 1)] = filter;
			for (let x = 0; x < stride; x += 1) {
				const a = x >= 4 ? orig[y][x - 4] : 0;
				const b = y > 0 ? orig[y - 1][x] : 0;
				const c = x >= 4 && y > 0 ? orig[y - 1][x - 4] : 0;
				const p = a + b - c;
				const pred = filter === 1 ? a : filter === 2 ? b : filter === 3 ? Math.floor((a + b) / 2) : Math.abs(p - a) <= Math.abs(p - b) && Math.abs(p - a) <= Math.abs(p - c) ? a : Math.abs(p - b) <= Math.abs(p - c) ? b : c;
				px(y)[x] = (orig[y][x] - pred) & 0xff;
			}
		}
		const rebuilt = png(4, 3, () => [0, 0, 0, 0]);
		const idat = require('zlib').deflateSync(raw);
		const head = rebuilt.subarray(0, ihdrEnd);
		const len = Buffer.alloc(4);
		len.writeUInt32BE(idat.length);
		const body = Buffer.concat([Buffer.from('IDAT'), idat]);
		const filtered = Buffer.concat([head, len, body, Buffer.alloc(4), rebuilt.subarray(rebuilt.length - 12)]);
		assert.deepStrictEqual(lane.pngInfo(filtered), lane.pngInfo(plain), `filter ${filter}`);
	}
});

test('viewsVerdict: listed after a switch, re-sampled with the seed, at most 200 pinned, the restore line', () => {
	const saved = { seed: 7, selection: 300 };
	const apply = { input: { seed: 7, include_keys: Array.from({ length: 200 }, (_, i) => ['o', i]) } };
	const line = '260 of 300 selected points restored; 40 drawn hollow';
	assert.strictEqual(lane.viewsVerdict({ listedAfterSwitch: true, saved, apply, line }), true);
	const broken = {
		'not listed': { listedAfterSwitch: false },
		'no sample': { apply: null },
		'another seed': { apply: { input: { seed: 8, include_keys: [] } } },
		'too many pinned': { apply: { input: { seed: 7, include_keys: Array.from({ length: 201 }, (_, i) => ['o', i]) } } },
		'no line': { line: '' },
		'another selection': { line: '260 of 299 selected points restored' },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.viewsVerdict({ listedAfterSwitch: true, saved, apply, line, ...change }), true, what);
});

test('dedupeVerdict: two groups for the two planted pairs, the shortest path kept, the slider with no sample request', () => {
	const groups = [
		[`${D}handbooks/falcon_handbook.md`, `${D}handbooks/falcon_handbook_rev2.md`],
		[`${D}field/kestrel_field_guide.md`, `${D}archive/kestrel_field_guide_copy.md`],
	];
	const keptPaths = [`${D}handbooks/falcon_handbook.md`, `${D}field/kestrel_field_guide.md`];
	const sound = { groups, keptPaths, samplesSent: 0, thresholdAfter: '0.92' };
	assert.strictEqual(lane.dedupeVerdict(sound), true);
	const broken = {
		'a pair split': { groups: [[groups[0][0]], [groups[0][1]], groups[1]] },
		'one group': { groups: [[...groups[0], ...groups[1]]] },
		'rev2 kept': { keptPaths: [groups[0][1], groups[1][0]] },
		'slider not moved': { thresholdAfter: '0.97' },
		're-sampled': { samplesSent: 1 },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.dedupeVerdict({ ...sound, ...change }), true, what);
});

test('removalVerdict: exactly the expected documents, batches of at most 100, the stats dropped by them', () => {
	const before = { documents: 40, chunks: 300 };
	const sound = { expected: ['a', 'b'], sent: [{ object_ids: ['a', 'b'] }], before, after: { documents: 38, chunks: 288 }, chunks: 12 };
	assert.strictEqual(lane.removalVerdict(sound), true);
	assert.strictEqual(lane.removalVerdict({ ...sound, sent: [{ object_id: 'a' }, { object_id: 'b' }] }), true);
	const broken = {
		'one more': { sent: [{ object_ids: ['a', 'b', 'c'] }] },
		'one fewer': { sent: [{ object_ids: ['a'] }] },
		'a batch above 100': { expected: Array.from({ length: 101 }, (_, i) => `d${i}`), sent: [{ object_ids: Array.from({ length: 101 }, (_, i) => `d${i}`) }], after: { documents: -61, chunks: 0 }, chunks: null },
		'stats unchanged': { after: before },
		'chunks unchanged': { after: { documents: 38, chunks: 300 } },
		'not read': { after: null },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.removalVerdict({ ...sound, ...change }), true, what);
});

test('outliersVerdict: the OCR junk first with its why, more rows at 5 %, no sample request', () => {
	const sample = sampleOf();
	const rows1 = [`${D}scans/ocr_scan_0417.txt #18 · density 0.12 vs sample median 0.61; nearest neighbour 0.31`, `${D}scans/ocr_scan_0417.txt #19 · density 0.15 vs sample median 0.61`];
	const rows5 = [...rows1, 'x', 'y'];
	assert.strictEqual(lane.outliersVerdict({ sample, rows1, rows5, samplesSent: 0 }), true);
	assert.notStrictEqual(lane.outliersVerdict({ sample: sampleOf({ outliers: [0, 18] }), rows1, rows5, samplesSent: 0 }), true, 'the manual first');
	assert.notStrictEqual(lane.outliersVerdict({ sample, rows1: rows1.slice(0, 1), rows5, samplesSent: 0 }), true, 'a row missing');
	assert.notStrictEqual(lane.outliersVerdict({ sample, rows1: [`${D}scans/ocr_scan_0417.txt #18`, rows1[1]], rows5, samplesSent: 0 }), true, 'no why');
	assert.notStrictEqual(lane.outliersVerdict({ sample, rows1, rows5: rows1, samplesSent: 0 }), true, '5 % added nothing');
	assert.notStrictEqual(lane.outliersVerdict({ sample, rows1, rows5, samplesSent: 2 }), true, 're-sampled');
});

test('chartsVerdict: the long manual in the top bin; clicking it scopes the directory to it', () => {
	const documents = [
		{ path: `${D}manuals/long_manual.md`, chunks: 160 },
		{ path: `${D}ops/memo_q1.txt`, chunks: 3 },
	];
	const sound = { topBin: '1 document with 128 to 255 chunks', documents, directory: [`${D}manuals/long_manual.md`], chip: true };
	assert.strictEqual(lane.chartsVerdict(sound), true);
	assert.notStrictEqual(lane.chartsVerdict({ ...sound, topBin: null }), true);
	assert.notStrictEqual(lane.chartsVerdict({ ...sound, chip: false }), true);
	assert.notStrictEqual(lane.chartsVerdict({ ...sound, directory: [`${D}ops/memo_q1.txt`] }), true);
	assert.notStrictEqual(lane.chartsVerdict({ ...sound, directory: [`${D}manuals/long_manual.md`, `${D}ops/memo_q1.txt`] }), true);
	assert.notStrictEqual(lane.chartsVerdict({ ...sound, documents: [documents[1]] }), true);
});

test('scopeVerdict: the status follows filter_applied; the directory, the sample and the chat stay inside; the saved filter applies again', () => {
	const prefix = `${D}handbooks/`;
	const scopeIds = ['o-falcon', 'o-rev2'];
	const sample = { docs: [{ objectId: 'o-falcon' }, { objectId: 'o-rev2' }] };
	const sound = { prefix, listing: { success: true, filter_applied: 'server' }, status: '2 documents match (store)', directory: [`${prefix}falcon_handbook.md`, `${prefix}falcon_handbook_rev2.md`], sampleInput: { filter: { object_ids: scopeIds } }, sample, scopeIds, sources: [`${prefix}falcon_handbook.md`], reapplied: true };
	assert.strictEqual(lane.scopeVerdict(sound), true);
	assert.strictEqual(lane.scopeVerdict({ ...sound, listing: { success: true, filter_applied: 'none' }, status: '2 of 40 loaded match (filtered here; the store cannot filter by these)' }), true);
	assert.strictEqual(lane.scopeVerdict({ ...sound, listing: { success: true, filter_applied: 'partial' }, status: '2 documents match (store; ingest dates filtered here)' }), true);
	const broken = {
		'server claimed, filtered here': { status: '2 of 40 loaded match (filtered here)' },
		'client claimed, store': { listing: { success: true, filter_applied: 'none' } },
		'a row outside': { directory: [...sound.directory, `${D}ops/memo_q1.txt`] },
		'an empty directory': { directory: [] },
		'sample not scoped': { sampleInput: { filter: { object_ids: null } } },
		'sample scope differs': { sampleInput: { filter: { object_ids: ['o-falcon'] } } },
		'a sampled document outside': { sample: { docs: [...sample.docs, { objectId: 'o-ocr' }] } },
		'a source outside': { sources: [`${D}ops/memo_q1.txt`] },
		'no source': { sources: [] },
		'not reapplied': { reapplied: false },
	};
	for (const [what, change] of Object.entries(broken)) assert.notStrictEqual(lane.scopeVerdict({ ...sound, ...change }), true, what);
});

test('scope600Verdict and listingVerdict: the whole scope sampled; the cap said where it applies', () => {
	const ids = Array.from({ length: 600 }, (_, i) => `pad-${i}`);
	const sample = { docs: ids.map((objectId) => ({ objectId })), listing: { documents: 600, truncated: false, reason: 'complete' } };
	assert.strictEqual(lane.scope600Verdict({ sampleInput: { filter: { object_ids: ids } }, sample, scopeIds: ids }), true);
	assert.match(lane.scope600Verdict({ sampleInput: { filter: { object_ids: ids } }, sample: { docs: sample.docs.slice(0, 500) }, scopeIds: ids }), /100 scoped documents/);
	assert.match(lane.scope600Verdict({ sampleInput: { filter: { object_ids: ids.slice(0, 500) } }, sample, scopeIds: ids }), /scoped to 500/);
	assert.match(lane.scope600Verdict({ sampleInput: { filter: { object_ids: ids } }, sample, scopeIds: ids.slice(0, 40) }), /resolved to 40/);
	assert.notStrictEqual(lane.scope600Verdict({ sampleInput: { filter: { object_ids: ids } }, sample: { docs: [...sample.docs, { objectId: 'o-ocr' }] }, scopeIds: ids }), true);
	const capped = { listing: { documents: 500, truncated: true, reason: 'cap' }, caveats: ['listing_truncated'] };
	const legend = 'Map legend · Sampled from the first 500 documents by path; the collection has more';
	assert.strictEqual(lane.listingVerdict({ sample: capped, legend, documents: 640 }), true);
	assert.notStrictEqual(lane.listingVerdict({ sample: capped, legend, documents: 40 }), true, 'not above the cap');
	assert.notStrictEqual(lane.listingVerdict({ sample: { ...capped, listing: { documents: 500, truncated: true, reason: 'stale' } }, legend, documents: 640 }), true);
	assert.notStrictEqual(lane.listingVerdict({ sample: { ...capped, caveats: [] }, legend, documents: 640 }), true);
	assert.notStrictEqual(lane.listingVerdict({ sample: capped, legend: 'Map legend', documents: 640 }), true);
});

test('keywordVerdict, thresholdVerdict, compareVerdict, layoutVerdict: the search workbench', () => {
	const input = { query: 'KX4471', mode: 'keyword', top_k: 10 };
	const answer = { results: [{ metadata: { parent: `${D}ops/memo_q3.txt`, objectId: 'o-q3', chunkId: 2 } }] };
	assert.strictEqual(lane.keywordVerdict({ input, answer, firstRow: '1 C:/demo/ops/memo_q3.txt #2 …' }), true);
	assert.notStrictEqual(lane.keywordVerdict({ input: { ...input, mode: 'semantic' }, answer, firstRow: 'ops/memo_q3.txt' }), true);
	assert.notStrictEqual(lane.keywordVerdict({ input: { ...input, vector: [0.1] }, answer, firstRow: 'ops/memo_q3.txt' }), true);
	assert.notStrictEqual(lane.keywordVerdict({ input, answer: { results: [] }, firstRow: 'ops/memo_q3.txt' }), true);
	assert.notStrictEqual(lane.keywordVerdict({ input, answer, firstRow: 'ops/memo_q1.txt' }), true);
	const low = "At 0.30: 11 of 20 pass (today's node setting)";
	const high = "At 0.60: 4 of 20 would pass (today's node setting 0.30 passes 11)";
	assert.strictEqual(lane.thresholdVerdict({ low, high, copied: 'threshold_search: 0.60' }), true);
	assert.notStrictEqual(lane.thresholdVerdict({ low, high: 'At 0.60: 11 of 20 would pass', copied: 'threshold_search: 0.60' }), true);
	assert.notStrictEqual(lane.thresholdVerdict({ low, high: 'At 0.60: 4 of 19 would pass', copied: 'threshold_search: 0.60' }), true);
	assert.notStrictEqual(lane.thresholdVerdict({ low, high, copied: 'threshold_search: 0.30' }), true);
	assert.notStrictEqual(lane.thresholdVerdict({ low: '', high, copied: 'threshold_search: 0.60' }), true);
	const r = (ids) => ({ results: ids.map((id) => ({ metadata: { objectId: id, chunkId: 0 } })) });
	const a = r(['a', 'b', 'c', 'd']);
	const b = r(['c', 'd', 'e', 'f']);
	const summary = 'A and B share 2 of 4 results (Jaccard 0.33); 2 documents only in A, 2 only in B';
	assert.strictEqual(lane.compareVerdict({ a, b, summary, starA: 'placed', starB: 'placed' }), true);
	assert.notStrictEqual(lane.compareVerdict({ a, b, summary: summary.replace('share 2', 'share 3'), starA: 'placed', starB: 'placed' }), true);
	assert.notStrictEqual(lane.compareVerdict({ a, b, summary: summary.replace('0.33', '0.50'), starA: 'placed', starB: 'placed' }), true);
	assert.notStrictEqual(lane.compareVerdict({ a, b, summary, starA: 'placed', starB: 'none' }), true);
	assert.notStrictEqual(lane.compareVerdict({ a, b: r([]), summary, starA: 'placed', starB: 'placed' }), true);
	assert.strictEqual(lane.layoutVerdict({ before: 0.55, after: 0.551 }), true);
	assert.notStrictEqual(lane.layoutVerdict({ before: 0.55, after: 1 }), true);
	assert.notStrictEqual(lane.layoutVerdict({ before: null, after: 0.55 }), true);
});

test('ingestVerdict and healthVerdict: the drop summary and the pin; the legacy listing flagged', () => {
	const keys = Array.from({ length: 9 }, (_, i) => ['o', i]);
	const sound = { summary: 'Drop of 3 files: 3 added (9 chunks)', files: 3, chunks: 9, project: { keys }, placed: '' };
	assert.strictEqual(lane.ingestVerdict(sound), true);
	assert.notStrictEqual(lane.ingestVerdict({ ...sound, summary: 'Drop of 3 files: 2 added (9 chunks)' }), true);
	assert.notStrictEqual(lane.ingestVerdict({ ...sound, chunks: 10 }), true);
	assert.notStrictEqual(lane.ingestVerdict({ ...sound, project: { keys: [] } }), true);
	assert.notStrictEqual(lane.ingestVerdict({ ...sound, project: { keys: keys.slice(0, 5) } }), true);
	const many = { summary: 'Drop of 3 files: 3 added (450 chunks)', files: 3, chunks: 450, project: { keys: Array.from({ length: 200 }, (_, i) => ['o', i]) }, placed: '200 of 450 new chunks placed' };
	assert.strictEqual(lane.ingestVerdict(many), true);
	assert.notStrictEqual(lane.ingestVerdict({ ...many, placed: '' }), true, 'a capped pin must say so');
	assert.notStrictEqual(lane.ingestVerdict({ ...many, project: { keys: Array.from({ length: 201 }, (_, i) => ['o', i]) } }), true);
	const items = [
		{ path: '/srv/legacy/manuals/long_manual.md', has_first_chunk: false, deleted_chunks: 0 },
		{ path: '/srv/legacy/ops/memo_q2.txt', has_first_chunk: true, deleted_chunks: 1 },
		{ path: '/srv/legacy/ops/memo_q1.txt', has_first_chunk: true, deleted_chunks: 0 },
	];
	const flagged = [
		{ path: items[0].path, kind: 'no_first_chunk' },
		{ path: items[1].path, kind: 'deleted_chunks' },
	];
	assert.strictEqual(lane.healthVerdict({ items, flagged }), true);
	assert.notStrictEqual(lane.healthVerdict({ items, flagged: flagged.slice(0, 1) }), true);
	assert.notStrictEqual(lane.healthVerdict({ items, flagged: flagged.slice(1) }), true);
	assert.notStrictEqual(lane.healthVerdict({ items: items.map((it) => ({ ...it, deleted_chunks: null })), flagged }), true, 'a store that does not count deleted chunks');
	assert.notStrictEqual(lane.healthVerdict({ items: items.slice(1), flagged }), true);
});

// ---------------------------------------------------------------------------
// What the lane looks for exists in the app's source (once the owning lane's code is on this branch)
// ---------------------------------------------------------------------------

const SRC = path.join(ACC, '..', '..', '..', 'apps', 'vector-ui', 'src');
const src = (file) => (fs.existsSync(path.join(SRC, file)) ? fs.readFileSync(path.join(SRC, file), 'utf8') : null);
/** The NEEDS reason while `file` is still the day-0 placeholder (or lacks the owning lane's marker), else false. */
const needs = (lanes, file, marker) => {
	const text = src(file);
	const built = text !== null && (marker ? text.includes(marker) : !text.includes('data-placeholder'));
	return built ? false : `NEEDS:${lanes} merged — integration gate GE2 (${file} is not built on this branch)`;
};
const SOURCES = [
	['E5', 'views/MapView.tsx', 'data-edge-mode', ['data-colour-by', 'data-edge-count', 'data-edges-hovered', 'data-min-cluster-size', 'data-shown', 'data-isolated', 'data-query-b-state']],
	['E5', 'components/MapToolbar.tsx', 'aria-label="Edges per point"', ['aria-label="Edges"', 'aria-label="Edges per point"', 'aria-label="Colour by"', 'Expand selected']],
	['E5', 'components/ClustersPanel.tsx', null, ['aria-label="Minimum size"', 'aria-label="Clusters by size"', 'Ask about the documents of cluster ${', 'in no group']],
	['E5', 'map/colours.ts', "'ingest-date'", ["label: 'Cluster'", "label: 'Ingest date'", 'oldest (${', 'newest (${']],
	['E5', 'components/Legend.tsx', 'Colour ramp from', ['Colour ramp from ${']],
	['E5', 'map/wording.ts', 'listingNote', ['Sampled from the first ${num(listing.documents)} documents by path; the collection has more']],
	['E6', 'components/DuplicatesPanel.tsx', 'Near-duplicate review', ['aria-label="Near-duplicate review"', 'aria-label="Near-duplicate similarity threshold"', 'aria-label="Which document each group keeps"', 'data-threshold', 'fieldset', 'Show group']],
	['E6', 'map/reviewWording.ts', 'removeAllLabel', ['Remove all queued (${', "'shortest-path'", 'Keep shortest path']],
	['E6', 'components/OutliersPanel.tsx', 'data-component="OutliersPanel"', ['Remove document', '<select', 'sample median']],
	['E6', 'components/PointInspector.tsx', 'Add as example', ['Add as example (+)', 'Add as example (−)', 'Show full text']],
	['E6', 'components/RecommendPanel.tsx', null, ['aria-label="Strategy"', 'Best score', 'Run']],
	['E6', 'components/SimilarityMatrix.tsx', null, ['Export CSV']],
	['E6', 'components/ChunkTextPanel.tsx', null, ['<mark']],
	['E7', 'components/ChatPanel.tsx', 'Search without the LLM', ['Search without the LLM', 'aria-pressed']],
	['E7', 'components/SearchPanel.tsx', null, ['aria-label="Search the collection"', 'aria-label="Compare with"', 'aria-label="Search mode"', 'aria-label="Threshold"', 'Copy as node setting', 'Compare']],
	['E8', 'components/ExportMenu.tsx', null, ['data-export-item', 'data-export-format', 'role="menuitem"']],
	['E8', 'components/SavedViewsMenu.tsx', null, ['Save current view', 'aria-label="Name of the view"', 'Apply view ${', 'selected points restored']],
	['E9', 'components/UploadList.tsx', 'Drop of', ['data-component="IngestSummary"', 'Show new chunks on the map', 'new chunks placed']],
	['E4', 'components/ScopeBar.tsx', null, ['Add condition', 'aria-label="Folder the paths start with"', 'aria-label="Name of the saved filter"', 'Apply saved filter ${', 'Remove condition: ${', 'Save…', 'Clear']],
	['E4', 'components/StatsCharts.tsx', null, ['data-chart={chart.id}', 'aria-label={words}']],
	['E4', 'components/DocumentRow.tsx', 'data-flag', ['data-object-id={item.objectId}', 'data-flag']],
];
for (const [owner, file, marker, patterns] of SOURCES) {
	test(`the lane's selectors for ${file} exist in the app's source`, { skip: needs(owner, file, marker) }, () => {
		const text = src(file);
		for (const p of patterns) assert.ok(text.includes(p), `${file} has no ${JSON.stringify(p)}`);
	});
}

// ---------------------------------------------------------------------------
// The perf lane's edge rows (lane_vector_perf.cjs; the app's map.perflane.test.ts pins the same gates)
// ---------------------------------------------------------------------------

test('perf lane: each edge mode is its own gate at 2,000 detailed points and 4x, measured with the slow-frame switch off', () => {
	const perf = require('../browser/lane_vector_perf.cjs');
	assert.deepStrictEqual(perf.EDGE_MODES, ['none', 'tree', 'neighbours:3', 'neighbours:5']);
	assert.deepStrictEqual(perf.PERF_LANE_FLAGS, { edgesAutoDegrade: false });
	assert.deepStrictEqual(perf.edgeModeOf('edges:neighbours:5'), { edges: 'neighbours', m: 5 });
	assert.deepStrictEqual(perf.edgeModeOf('tree'), { edges: 'tree', m: null });
	assert.strictEqual(perf.edgeLimit('tree', 2000), 1999);
	assert.strictEqual(perf.edgeLimit('neighbours:3', 2000), 6000);
	assert.strictEqual(perf.edgeLimit('none', 2000), 0);
	const frames = (count, ms) => Array.from({ length: count }, () => ms);
	const base = { n: 2000, mode: 'detailed', cpuThrottle: 4, renderer: 'webgl', panFrameMs: perf.summarise(frames(80, 18)), panWork: { draws: 74, cameraBefore: '2d:0,0,40', cameraAfter: '2d:3,1,40' }, privacy: { frames: 120, dimension: 384, embedAnswers: 0, vectorRequests: 0, violations: [] } };
	const drawn = { none: 0, tree: 1999, 'neighbours:3': 5400, 'neighbours:5': 8800 };
	const row = (mode, extra = {}) => ({ ...base, edges: `edges:${mode}`, edgesAutoDegrade: false, edgesDegraded: false, edgesDrawn: drawn[mode], ...(mode.startsWith('neighbours') ? { edgesPerPoint: Number(mode.split(':')[1]) } : {}), ...extra });
	const gate = (rows, mode) => perf.evaluateGates(rows).find((g) => g.name.startsWith(`GATE edges:${mode} `));
	const all = [{ ...base, edgeModes: perf.EDGE_MODES }, ...perf.EDGE_MODES.map((m) => row(m))];
	for (const mode of perf.EDGE_MODES) assert.strictEqual(gate(all, mode).status, 'PASS', `${mode}: ${gate(all, mode).detail}`);
	const broken = {
		'switch on': { edgesAutoDegrade: true },
		'switch unrecorded': { edgesAutoDegrade: undefined },
		degraded: { edgesDegraded: true },
		'edges unread': { edgesDrawn: null },
		'too slow': { panFrameMs: perf.summarise([...frames(60, 20), ...frames(20, 60)]) },
		'nothing drawn by the pan': { panWork: { draws: 2, cameraBefore: '2d:0,0,40', cameraAfter: '2d:3,1,40' } },
		errored: { error: 'the edge layer never drew' },
	};
	for (const mode of perf.EDGE_MODES) {
		for (const [what, extra] of Object.entries(broken)) {
			const rows = [{ ...base, edgeModes: perf.EDGE_MODES }, ...perf.EDGE_MODES.map((m) => (m === mode ? row(m, extra) : row(m)))];
			assert.strictEqual(gate(rows, mode).status, 'FAIL', `${mode} ${what}`);
		}
	}
	// Mode-specific: edges at None, none in a drawing mode, more than the mode allows, fewer per point than asked.
	assert.strictEqual(perf.edgeRowProblem(row('none', { edgesDrawn: 3 }), 'none') !== null, true);
	assert.strictEqual(perf.edgeRowProblem(row('tree', { edgesDrawn: 0 }), 'tree') !== null, true);
	assert.strictEqual(perf.edgeRowProblem(row('tree', { edgesDrawn: 2000 }), 'tree') !== null, true);
	assert.strictEqual(perf.edgeRowProblem(row('neighbours:5', { edgesPerPoint: 3 }), 'neighbours:5') !== null, true);
	assert.strictEqual(perf.edgeRowProblem(row('neighbours:5', { edgesPerPoint: null }), 'neighbours:5') !== null, true);
	// A run whose points row was due to carry edge rows but has none reports every edge gate as not measured.
	const missing = perf.evaluateGates([{ ...base, edgeModes: perf.EDGE_MODES }]).filter((g) => g.name.startsWith('GATE edges:'));
	assert.deepStrictEqual(
		missing.map((g) => [g.status, g.detail]),
		perf.EDGE_MODES.map(() => ['FAIL', 'not measured'])
	);
	// The 1x rows are measured, not gated; the points gate stays the row without edges.
	const at1 = perf.evaluateGates([...all, ...perf.EDGE_MODES.map((m) => row(m, { cpuThrottle: 1, edgesAutoDegrade: true }))]);
	assert.ok(at1.filter((g) => g.name.startsWith('GATE edges:')).every((g) => g.status === 'PASS'));
	assert.match(at1[0].name, /^GATE 2,000 detailed points at 4x/);
	// Each edge row carries its own privacy row, named with its mode.
	assert.ok(at1.some((g) => /^privacy \(B4\).*edges:tree at 4x/.test(g.name)));
});
