// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// THE GRAPH SESSION: expand, collapse, dismiss, connect, find path, refresh
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createGraphSession } from '../src/graph/graphSession';
import type { IGraphSessionDeps } from '../src/graph/graphSession';
import type { IFailureNotice } from '../src/graph/failures';
import type { GraphValue, ReadQueryResult } from '../src/graph/types';
import type { IEngine, IRecipe } from '../src/cypher/recipes';
import { node, readQueryFixture, rel } from './support/builders';

const NEO: IEngine = { dialect: 'neo4j', version: '5.26.31' };
const AGE: IEngine = { dialect: 'age', version: '1.5.0' };

const envelope = (rows: GraphValue[][], extra: Partial<ReadQueryResult> = {}): ReadQueryResult => ({ columns: rows[0]?.map((_, i) => `c${i}`) ?? ['c'], rows, row_limit: 1000, truncated: false, truncated_by: null, element_limit: 10000, elements: 0, value_limit: 500000, values: 0, ...extra });
const notice = (headline: string, over: Partial<IFailureNotice> = {}): IFailureNotice => ({ variant: 'error', headline, detail: '', verbatim: '', generic: false, hint: null, ignore: false, ...over });

/** A session over a scripted node. */
function rig(engine: IEngine | null = NEO, answer: (recipe: IRecipe, call: number) => Promise<ReadQueryResult> | ReadQueryResult = () => envelope([[]])) {
	const log = { recipes: [] as IRecipe[], said: [] as string[] };
	const deps: IGraphSessionDeps = {
		engine: () => engine,
		invoke: async (recipe) => {
			log.recipes.push(recipe);
			return answer(recipe, log.recipes.length - 1);
		},
		describe: (error) => notice(error instanceof Error ? error.message : String(error)),
		announce: (text) => log.said.push(text),
		captionChoice: () => undefined,
	};
	const session = createGraphSession(deps);
	return { session, log };
}
const base = (): ReadQueryResult => envelope([[node('a', ['P'], { name: 'A' }), node('b', ['P'], { name: 'B' }), rel('r1', 'T', 'a', 'b')]]);
const tick = () => new Promise((r) => setImmediate(r));

test('loading a result draws its nodes, focuses the first and clears everything else', () => {
	const { session } = rig();
	session.load(base());
	const s = session.getState();
	assert.deepEqual([...s.model.nodes.keys()], ['a', 'b']);
	assert.equal(s.focusedId, 'a');
	assert.equal(s.selected.size, 0);
	assert.equal(s.busy, null);
	session.load(envelope([[1, 2]]));
	assert.equal(session.getState().model.nodes.size, 0, 'a scalar-only result draws nothing');
	session.load(null);
	assert.equal(session.getState().entities, null);
});

test('selection toggles and is announced with a count', () => {
	const { session, log } = rig();
	session.load(base());
	session.toggleSelect('a');
	session.toggleSelect('b');
	assert.deepEqual([...session.getState().selected], ['a', 'b']);
	assert.deepEqual(log.said.slice(-2), ['A selected. 1 node selected.', 'B selected. 2 nodes selected.']);
	session.toggleSelect('a');
	assert.equal(log.said[log.said.length - 1], 'A deselected. 1 node selected.');
	session.clearSelection();
	assert.equal(session.getState().selected.size, 0);
});

test('expand sends one parameterised read_query, draws only NEW neighbours and says what happened', async () => {
	const { session, log } = rig(NEO, () => envelope([[node('a'), rel('r2', 'T', 'a', 'c'), node('c', ['P'], { name: 'C' })], [node('a'), rel('r1', 'T', 'a', 'b'), node('b')]]));
	session.load(base());
	await session.expand('a');
	assert.equal(log.recipes.length, 1);
	assert.deepEqual(log.recipes[0].params, { id: 'a' });
	assert.ok(!log.recipes[0].cypher.includes("'a'"));
	const s = session.getState();
	assert.deepEqual([...s.model.nodes.keys()], ['a', 'b', 'c']);
	assert.deepEqual(s.hint, { centerId: 'a', newIds: ['c'] });
	assert.equal(s.busy, null);
	assert.equal(s.notice?.text, 'Added 1 neighbour.');
	assert.equal(log.said[log.said.length - 1], 'Added 1 neighbour.');
	// The relationship that was already drawn is not duplicated.
	assert.equal(s.model.relationships.size, 2);
});

test('an expansion that fills its row allowance says more may exist', async () => {
	const rows = Array.from({ length: 5 }, (_, i) => [node('a'), rel(`x${i}`, 'T', 'a', `n${i}`), node(`n${i}`)] as GraphValue[]);
	const { session } = rig(NEO, (recipe) => envelope(rows, { row_limit: recipe.limit }));
	session.load(envelope([[node('a')]]));
	// ask for exactly the rows the answer holds: wanted 100 + shown 0 + 1 = 101, so 5 rows is NOT incomplete...
	await session.expand('a');
	assert.equal(session.getState().notice?.text, 'Added 5 neighbours.');
	// ...but a truncated answer is.
	const { session: s2 } = rig(NEO, () => envelope(rows, { truncated: true, truncated_by: 'rows' }));
	s2.load(envelope([[node('a')]]));
	await s2.expand('a');
	assert.match(s2.getState().notice?.text ?? '', /This node has more relationships than were fetched; expand again for more\./);
});

test('only one request at a time: a second action is declined with a sentence and sends nothing', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { session, log } = rig(NEO, () => new Promise<ReadQueryResult>((resolve) => { release = resolve; }));
	session.load(base());
	const first = session.expand('a');
	await tick();
	assert.equal(session.getState().busy, 'expand');
	await session.expand('b');
	await session.connect();
	assert.equal(log.recipes.length, 1);
	assert.match(session.getState().notice?.text ?? '', /Another request is still running/);
	release(envelope([[node('a'), rel('r2', 'T', 'a', 'c'), node('c')]]));
	await first;
	assert.equal(session.getState().busy, null);
});

test('a result loaded while an expansion is in flight wins: the late answer is dropped', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { session } = rig(NEO, () => new Promise<ReadQueryResult>((resolve) => { release = resolve; }));
	session.load(base());
	const pending = session.expand('a');
	await tick();
	session.load(envelope([[node('z', ['Q'])]]));
	release(envelope([[node('a'), rel('r2', 'T', 'a', 'c'), node('c')]]));
	await pending;
	const s = session.getState();
	assert.deepEqual([...s.model.nodes.keys()], ['z'], 'the new result is untouched by the old answer');
	assert.equal(s.busy, null);
	assert.equal(s.notice, null);
});

test('dispose drops everything in flight', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { session, log } = rig(NEO, () => new Promise<ReadQueryResult>((resolve) => { release = resolve; }));
	session.load(base());
	const pending = session.expand('a');
	await tick();
	session.dispose();
	release(envelope([[node('a'), rel('r2', 'T', 'a', 'c'), node('c')]]));
	await pending;
	assert.deepEqual([...session.getState().model.nodes.keys()], ['a', 'b']);
	assert.ok(!log.said.some((s) => /Added/.test(s)));
});

test('a failed expansion keeps the canvas as it was and shows the node\'s text', async () => {
	const { session } = rig(NEO, () => { throw new Error('Query timed out after 30000 ms'); });
	session.load(base());
	await session.expand('a');
	const s = session.getState();
	assert.equal(s.model.nodes.size, 2);
	assert.equal(s.busy, null);
	assert.equal(s.notice?.variant, 'error');
	assert.equal(s.notice?.text, 'Query timed out after 30000 ms');
});

test('an element that is no longer found is said to be, not replaced by another', async () => {
	const { session } = rig(NEO, () => envelope([]));
	session.load(base());
	await session.expand('a');
	assert.match(session.getState().notice?.text ?? '', /no longer found: element ids are live handles\. Nothing was added\./);
	assert.equal(session.getState().model.nodes.size, 2);
});

test('expanding without a probed engine sends nothing and says why', async () => {
	const { session, log } = rig(null);
	session.load(base());
	await session.expand('a');
	assert.equal(log.recipes.length, 0);
	assert.match(session.getState().notice?.text ?? '', /has not been checked yet/);
});

test('collapse removes what only hung from the node; dismiss removes a node and its relationships; both are local', async () => {
	const { session, log } = rig(NEO, () => envelope([[node('a'), rel('r2', 'T', 'a', 'c'), node('c')]]));
	session.load(base());
	session.collapse('a');
	assert.match(session.getState().notice?.text ?? '', /Nothing to collapse/);
	await session.expand('a');
	const calls = log.recipes.length;
	session.collapse('a');
	assert.deepEqual([...session.getState().model.nodes.keys()], ['a', 'b']);
	assert.match(session.getState().notice?.text ?? '', /^Collapsed\. 1 node removed from the graph\./);
	session.toggleSelect('b');
	session.dismiss('b');
	const s = session.getState();
	assert.deepEqual([...s.model.nodes.keys()], ['a']);
	assert.equal(s.model.relationships.size, 0);
	assert.equal(s.selected.has('b'), false);
	assert.match(s.notice?.text ?? '', /dismissed from the graph\. It is still in the results table\./);
	assert.equal(log.recipes.length, calls, 'no node call');
});

test('dismissing the focused node moves focus to a remaining one', () => {
	const { session } = rig();
	session.load(base());
	session.focus('a');
	session.dismiss('a');
	assert.equal(session.getState().focusedId, 'b');
});

test('connect asks for the relationships among the drawn nodes and adds only those; AGE is bounded', async () => {
	const { session, log } = rig(NEO, () => envelope([[node('a'), rel('r9', 'T', 'b', 'a'), node('b')]]));
	session.load(envelope([[node('a'), node('b')]]));
	await session.connect();
	assert.deepEqual(log.recipes[0].params, { ids: ['a', 'b'] });
	assert.equal(session.getState().model.relationships.size, 1);
	assert.equal(session.getState().notice?.text, 'Added 1 relationship among the nodes on the canvas.');
	await session.connect();
	assert.equal(session.getState().notice?.text, 'No further relationships among the nodes on the canvas.');
	const many = envelope([Array.from({ length: 41 }, (_, i) => node(`n${i}`))]);
	const { session: age, log: ageLog } = rig(AGE);
	age.load(many);
	await age.connect();
	assert.equal(ageLog.recipes.length, 0, 'refused before sending');
	assert.match(age.getState().notice?.text ?? '', /not supported on Apache AGE yet/);
});

test('find path needs exactly two selected nodes, merges the first path found, highlights it and keeps stored direction', async () => {
	const path = { '@kind': 'path', nodes: [node('a'), node('m'), node('b')], relationships: [rel('p1', 'T', 'a', 'm'), rel('p2', 'T', 'b', 'm')] };
	const { session, log } = rig(NEO, (recipe) => envelope(/\[\*2\.\.2\]/.test(recipe.cypher) ? [[path as unknown as GraphValue]] : []));
	session.load(base());
	await session.findPath();
	assert.match(session.getState().notice?.text ?? '', /Select exactly two nodes/);
	assert.equal(log.recipes.length, 0);
	session.toggleSelect('a');
	session.toggleSelect('b');
	await session.findPath();
	const s = session.getState();
	assert.deepEqual(log.recipes.map((r) => /\[\*(\d)\.\.\d\]/.exec(r.cypher)?.[1]), ['1', '2'], 'deepening stopped at the first depth that answered');
	assert.deepEqual([...s.highlight].sort(), ['p1', 'p2']);
	assert.ok(s.model.nodes.has('m'), 'the path\'s middle node joined the canvas');
	assert.equal(s.model.relationships.get('p2')?.start, 'b', 'stored direction kept');
	assert.match(s.notice?.text ?? '', /^Found a path of 2 relationships \(the first, so a shortest one\)\./);
	assert.equal(s.busy, null);
	assert.equal(s.progress, null);
});

test('no path within the depth limit is said in budget terms; Stop waiting is honest', async () => {
	const { session } = rig(NEO, () => envelope([]));
	session.load(base());
	session.toggleSelect('a');
	session.toggleSelect('b');
	await session.findPath();
	assert.match(session.getState().notice?.text ?? '', /^No path within depth 10\./);
	// Stop waiting mid-search.
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { session: s2, log } = rig(NEO, () => new Promise<ReadQueryResult>((resolve) => { release = resolve; }));
	s2.load(base());
	s2.toggleSelect('a');
	s2.toggleSelect('b');
	const running = s2.findPath();
	await tick();
	assert.equal(s2.getState().busy, 'path');
	assert.match(s2.getState().progress ?? '', /Looking for a path of 1 relationship/);
	s2.stopPath();
	await running;
	assert.equal(s2.getState().busy, null);
	assert.match(s2.getState().notice?.text ?? '', /^Stopped waiting\. Stop waiting stops this app/);
	release(envelope([]));
	await tick();
	assert.equal(log.recipes.length, 1, 'no further depth after stopping');
});

test('refreshing an inspected node updates the drawn copy, or says the element was not found', async () => {
	const { session } = rig(NEO, () => envelope([[node('a', ['P'], { name: 'Renamed' })]]));
	session.load(base());
	session.inspect({ kind: 'node', id: 'a' });
	await session.refreshInspected();
	assert.equal(session.getState().model.nodes.get('a')?.properties.name, 'Renamed');
	assert.equal(session.getState().notice?.text, 'Refreshed from the database.');
	const { session: gone } = rig(NEO, () => envelope([]));
	gone.load(base());
	gone.inspect({ kind: 'node', id: 'a' });
	await gone.refreshInspected();
	assert.match(gone.getState().notice?.text ?? '', /was not found any more\. Element ids are live handles/);
	assert.equal(gone.getState().model.nodes.get('a')?.properties.name, 'A', 'the drawn copy is left alone');
});

test('show more draws more of the same result, up to the canvas maximum', () => {
	const big = envelope([Array.from({ length: 600 }, (_, i) => node(`n${i}`))]);
	const { session } = rig();
	session.load(big);
	assert.equal(session.getState().model.nodes.size, 300);
	session.showMore();
	assert.equal(session.getState().model.nodes.size, 600);
	assert.match(session.getState().notice?.text ?? '', /^Showing 300 more nodes \(600 of 600\)\./);
	session.showMore();
	assert.match(session.getState().notice?.text ?? '', /already shows as many nodes as it can hold/);
});

test('the real fixtures load into a drawable session on every engine', () => {
	for (const engine of ['neo4j', 'falkordb', 'age'] as const) {
		const { session } = rig();
		session.load(readQueryFixture(engine, 'v1'));
		const s = session.getState();
		assert.equal(s.model.nodes.size, 3, engine);
		assert.equal(s.model.relationships.size, 5, engine);
	}
});

test('subscribers hear changes and can unsubscribe', () => {
	const { session } = rig();
	let heard = 0;
	const off = session.subscribe(() => { heard += 1; });
	session.load(base());
	session.focus('b');
	assert.equal(heard, 2);
	off();
	session.focus('a');
	assert.equal(heard, 2);
});
