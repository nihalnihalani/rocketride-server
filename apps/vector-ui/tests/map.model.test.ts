// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// MAP MODEL: keys, hidden points, PCA positions, neighbours and the sample label
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chunkPath, hiddenMask, keyIndex, keyString, neighboursOf, pcaPositions, pointKey, visibleCount } from '../src/map/model';
import { biasedNote, sampleLabel } from '../src/map/wording';
import { loadSample, modelOf } from './support/map.samples';

const demo = loadSample('sample_demo_1000.json');

test('every point has a key (objectId, chunkId), and the key index maps it back', () => {
	const index = keyIndex(demo);
	assert.equal(index.size, demo.n, 'keys are unique within a sample');
	for (const i of [0, 1, 499, 999]) {
		const key = pointKey(demo, i);
		assert.equal(key[0], demo.docs[demo.points.doc[i] as number]?.objectId);
		assert.equal(key[1], demo.points.chunk[i]);
		assert.equal(index.get(keyString(key[0], key[1])), i);
	}
});

test('points of removed documents are hidden; indices stay put', () => {
	assert.equal(hiddenMask(modelOf(demo)), null);
	const gone = demo.docs[0]?.objectId as string;
	const mask = hiddenMask(modelOf(demo, { removed: [gone] })) as Uint8Array;
	let hidden = 0;
	for (let i = 0; i < demo.n; i += 1) {
		assert.equal(mask[i], demo.points.doc[i] === 0 ? 1 : 0);
		hidden += mask[i] as number;
	}
	assert.equal(hidden, demo.docs[0]?.in_sample);
	assert.equal(visibleCount(modelOf(demo, { removed: [gone] })), demo.n - hidden);
	assert.equal(visibleCount(modelOf(demo)), demo.n);
});

test('PCA positions come from the answer\'s x, y (and z) columns', () => {
	const two = pcaPositions(demo, 2);
	const three = pcaPositions(demo, 3);
	assert.equal(two.length, demo.n * 2);
	assert.equal(three.length, demo.n * 3);
	assert.equal(two[2], Math.fround(demo.points.x[1] as number));
	assert.equal(three[5], Math.fround((demo.points.z as number[])[1] as number));
});

test('a document\'s chunk path lists its sampled points in chunk order', () => {
	const objectId = demo.docs[1]?.objectId as string;
	const path = chunkPath(demo, objectId);
	assert.equal(path.length, demo.docs[1]?.in_sample);
	const chunks = path.map((i) => demo.points.chunk[i] as number);
	assert.deepEqual(chunks, [...chunks].sort((a, b) => a - b));
	assert.deepEqual(chunkPath(demo, 'not-there'), []);
});

test('a point\'s neighbours come from the kNN block, nearest first, with their similarities', () => {
	const row = neighboursOf(demo, 5);
	assert.equal(row.length, demo.knn.k);
	assert.equal(row[0]?.i, demo.knn.cols[demo.knn.offsets_row[5] as number]);
	for (let r = 1; r < row.length; r += 1) assert.ok((row[r - 1]?.sim as number) >= (row[r]?.sim as number));
	assert.equal(neighboursOf(demo, 5, 3).length, 3);
});

test('the sample label says how many of how many, and whether the sample is uniform', () => {
	assert.equal(sampleLabel(demo), 'Showing 1,000 of 1,318 chunks (random sample)');
	const biased = loadSample('sample_biased_refilled.json');
	assert.equal(sampleLabel(biased), 'Showing 180 of 180 chunks (not a uniform sample); fewer points than requested: the store returned 180');
	assert.equal(biasedNote(biased), 'Some documents could not be sampled evenly, so the store filled the sample with other chunks.');
	assert.equal(biasedNote(demo), null);
	assert.equal(sampleLabel({ ...demo, strategy_used: 'first', biased: false }), 'Showing 1,000 of 1,318 chunks (not a uniform sample)');
	assert.equal(sampleLabel({ ...demo, of: { chunks: null, documents: null } }), 'Showing 1,000 chunks (random sample; the store did not say how many it holds)');
});
