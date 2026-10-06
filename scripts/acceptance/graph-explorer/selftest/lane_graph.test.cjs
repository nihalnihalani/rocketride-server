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

// The landing behind the drawer names every engine: in its subtitle and on the three fixture cards.
const LANDING_TEXT = ['Connections', 'Graph databases reachable through your running pipelines (Apache AGE, Neo4j, FalkorDB). A connection is a graph node in a pipeline.', 'AGE\nrocketride_graph · gx-local Graph (AGE)', 'Neo4j\ngraph_neo4j · gx-local Graph (Neo4j)', 'FalkorDB\ngraph_falkordb · gx-local Graph (FalkorDB)'].join('\n');
// A FalkorDB drawer as the app renders it once the node answered its identity probe.
const FALKORDB_DRAWER = `FalkorDB\ngraph_falkordb · gx-local Graph (FalkorDB)\nSTATUS\nRunning\nCONNECTION\nPipeline\ngx-local Graph (FalkorDB)\nNode\nFalkorDB (graph_falkordb)\nEngine\nFalkorDB 6.0.1\nTarget\ngraph gx_accept\nWrites\nOff (browsing only)\nTest connection\nOpen workbench`;

const DRAWER_STEP = 'drawer shows engine identity';
const drawerRow = (engine, text) => {
	const run = runWithStandIn('lane_graph.cjs', ['chrome', engine], 'lane_graph.json', { text, visible: true });
	const r = run.data.find((x) => x.name.startsWith(DRAWER_STEP));
	assert.ok(r, `the drawer step did not run:\n${run.stdout}`);
	return r;
};

test('lane_graph: the drawer step fails when only the landing names the engine', () => {
	const r = drawerRow('falkordb', LANDING_TEXT);
	assert.strictEqual(r.status, 'FAIL', `passed on engine names from the landing, with no Engine row in the drawer: ${JSON.stringify(r)}`);
});

test('lane_graph: the drawer step fails when the drawer shows another engine', () => {
	const r = drawerRow('neo4j', `${LANDING_TEXT}\n${FALKORDB_DRAWER}`);
	assert.strictEqual(r.status, 'FAIL', `the Neo4j lane passed on a drawer that says FalkorDB: ${JSON.stringify(r)}`);
});

test('lane_graph: the drawer step passes when the drawer shows the expected engine', () => {
	const r = drawerRow('falkordb', `${LANDING_TEXT}\n${FALKORDB_DRAWER}`);
	assert.strictEqual(r.status, 'PASS', JSON.stringify(r));
});
