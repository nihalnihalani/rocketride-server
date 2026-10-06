// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Self-test for browser/lane_graph.cjs's verdicts, without a browser or an engine:
 * the stand-in Playwright (stand_in.cjs) finds no element and reads empty text.
 * A step that could not test what it names must then be a FAIL, never a PASS.
 * Run: node --test scripts/acceptance/graph-explorer/selftest/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { runWithStandIn } = require('./stand_in.cjs');

let run;
const lane = () => (run ||= runWithStandIn('lane_graph.cjs', ['chrome', 'falkordb'], 'lane_graph.json'));
const row = (prefix) => {
	const r = lane().data.find((x) => x.name.startsWith(prefix));
	assert.ok(r, `the step "${prefix}" did not run:\n${lane().stdout}`);
	return r;
};

test('lane_graph: the Ask step fails when the ask bar is missing', () => {
	const ask = row('Ask without an LLM');
	assert.strictEqual(ask.status, 'FAIL', `Ask step passed without an ask bar: ${JSON.stringify(ask)}`);
});

test('lane_graph: the Escape step fails when no inspector was open', () => {
	const esc = row('Escape closes the inspector');
	assert.strictEqual(esc.status, 'FAIL', `Escape step passed without an open inspector: ${JSON.stringify(esc)}`);
});

test('lane_graph: exits non-zero when a step failed', () => {
	assert.notStrictEqual(lane().status, 0, 'lane exited 0 with failed steps');
});
