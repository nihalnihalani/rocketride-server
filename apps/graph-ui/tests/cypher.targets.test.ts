// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// WHAT RUN SENDS
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { describeRun, targetsToRun } from '../src/cypher/targets';

const BUFFER = 'MATCH (n) RETURN n;\nMATCH (m)\nRETURN m;\n// note\nRETURN 3';

test('Run sends the statement the caret is in, with its lines in the buffer', () => {
	const t = targetsToRun(BUFFER, { start: 25, end: 25 }, 25, false);
	assert.equal(t.length, 1);
	assert.equal(t[0].text, 'MATCH (m)\nRETURN m');
	assert.deepEqual([t[0].startLine, t[0].endLine], [2, 3]);
	assert.equal(BUFFER.slice(t[0].start, t[0].end), t[0].text);
});

test('Run sends the selection, split into statements with buffer offsets; Run all sends everything', () => {
	const from = BUFFER.indexOf('MATCH (n)');
	const to = BUFFER.indexOf('// note');
	const sel = targetsToRun(BUFFER, { start: from, end: to }, from, false);
	assert.deepEqual(sel.map((s) => s.text), ['MATCH (n) RETURN n', 'MATCH (m)\nRETURN m']);
	for (const s of sel) assert.equal(BUFFER.slice(s.start, s.end), s.text);
	const all = targetsToRun(BUFFER, { start: 3, end: 3 }, 3, true);
	assert.deepEqual(all.map((s) => s.text), ['MATCH (n) RETURN n', 'MATCH (m)\nRETURN m', '// note\nRETURN 3']);
	assert.deepEqual(all.map((s) => s.startLine), [1, 2, 4]);
});

test('an empty buffer, or one holding only comments, sends nothing', () => {
	assert.deepEqual(targetsToRun('', { start: 0, end: 0 }, 0, false), []);
	assert.deepEqual(targetsToRun('// nothing', { start: 0, end: 0 }, 0, true), []);
	assert.equal(describeRun('', { start: 0, end: 0 }, 0), 'Nothing to run.');
});

test('the "Will run" sentence names the lines and says it stops at the first error when several are selected', () => {
	assert.equal(describeRun(BUFFER, { start: 25, end: 25 }, 25), 'Will run: the statement at lines 2–3.');
	assert.equal(describeRun(BUFFER, { start: 0, end: 5 }, 0), 'Will run: the selection at line 1.');
	const from = BUFFER.indexOf('MATCH (n)');
	const to = BUFFER.indexOf('// note');
	assert.equal(describeRun(BUFFER, { start: from, end: to }, from), 'Will run: 2 statements from the selection (lines 1–3), in order, stopping at the first error.');
});
