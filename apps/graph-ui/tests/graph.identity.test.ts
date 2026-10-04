// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// ELEMENT IDENTITY AND DATA VERSIONS
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDataVersions, mayHaveChangedData } from '../src/graph/dataVersion';
import { conflictText, identityConflicts } from '../src/graph/identity';
import { modelFromResult } from '../src/graph/model';
import { entitiesOf, node, rel } from './support/builders';

const model = modelFromResult(entitiesOf([node('1', ['Person', 'Employee']), node('2', [])], [rel('r', 'KNOWS', '1', '2')]));

test('the same labels in any order, and any properties, are the same node; other labels are not', () => {
	assert.deepEqual(identityConflicts(model, [node('1', ['Employee', 'Person'], { name: 'changed' })], []), []);
	assert.deepEqual(identityConflicts(model, [node('2', [], { x: 1 })], []), []);
	const conflicts = identityConflicts(model, [node('1', ['Person']), node('2', ['Thing']), node('3', ['Anything'])], []);
	assert.deepEqual(conflicts.map((c) => [c.id, c.kind, c.drawn, c.returned]), [['1', 'node', 'labels Person, Employee', 'label Person'], ['2', 'node', 'no label', 'label Thing']]);
	assert.deepEqual(identityConflicts(model, [node('9', ['New'])], []), [], 'an id the canvas does not hold is just a new element');
});

test('a relationship is the same only with the same type, start and end', () => {
	assert.deepEqual(identityConflicts(model, [], [rel('r', 'KNOWS', '1', '2', { since: 1 })]), []);
	for (const other of [rel('r', 'LIKES', '1', '2'), rel('r', 'KNOWS', '2', '1'), rel('r', 'KNOWS', '1', '3')]) {
		const [conflict] = identityConflicts(model, [], [other]);
		assert.equal(conflict.kind, 'relationship');
		assert.equal(conflict.drawn, 'type KNOWS from 1 to 2');
	}
});

test('node and relationship ids are separate namespaces: a node id equal to a relationship id conflicts with nothing', () => {
	assert.deepEqual(identityConflicts(model, [node('r', ['Whatever'])], []), []);
	assert.deepEqual(identityConflicts(model, [], [rel('1', 'T', 'a', 'b')]), []);
});

test('the sentence names the first conflict, the count, and what to do', () => {
	const [one] = identityConflicts(model, [node('1', ['Other'])], []);
	assert.match(conflictText([one]), /a different element under an id drawn here \(the node 1 was labels Person, Employee, and is now label Other\)\. Ids can be reused after a delete, so nothing from this answer was added, and the drawn copy is marked out of date\. Dismiss it, or run the query again\./);
	assert.match(conflictText([one, one]), /2 different elements under ids/);
});

test('data versions count per connection and tell subscribers', () => {
	const versions = createDataVersions();
	let heard = 0;
	const stop = versions.subscribe(() => { heard += 1; });
	assert.equal(versions.get('a'), 0);
	versions.bump('a');
	versions.bump('a');
	versions.bump('b');
	assert.deepEqual([versions.get('a'), versions.get('b'), versions.get('c')], [2, 1, 0]);
	assert.equal(heard, 3);
	stop();
	versions.bump('a');
	assert.equal(heard, 3);
});

test('only the write console can change data, and only a success or an outcome nobody saw counts; a failed statement does not', () => {
	assert.equal(mayHaveChangedData('write', 'rows'), true);
	assert.equal(mayHaveChangedData('write', 'affected'), true);
	assert.equal(mayHaveChangedData('write', 'abandoned'), true, 'stopped waiting: it may still complete on the database');
	assert.equal(mayHaveChangedData('write', 'error'), false);
	assert.equal(mayHaveChangedData('write', 'skipped'), false);
	for (const outcome of ['rows', 'abandoned', 'error']) assert.equal(mayHaveChangedData('read', outcome), false, 'the read path cannot write');
});
