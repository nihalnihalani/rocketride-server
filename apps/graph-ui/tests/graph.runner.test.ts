// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// SEQUENTIAL STATEMENT RUNNER
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createBatchRunner, formatBatchOutcome } from '../src/graph/runner';
import type { IBatchDeps, IStatementRun } from '../src/graph/runner';
import { prepareStatement } from '../src/graph/runConfig';
import type { IFailureNotice } from '../src/graph/failures';
import type { ReadQueryResult } from '../src/graph/types';

const result = (n: number): ReadQueryResult => ({ columns: ['n'], rows: Array.from({ length: n }, (_, i) => [i]), row_limit: 1000, truncated: false, truncated_by: null, element_limit: 10000, elements: 0, value_limit: 500000, values: n });
const notice = (headline: string, ignore = false): IFailureNotice => ({ variant: 'error', headline, detail: '', hint: null, ignore });
const prepare = (...texts: string[]) => texts.map((t) => prepareStatement(t, 1000, null));

/** A rig around the runner with a scripted node. */
function rig(script: Array<() => Promise<ReadQueryResult>>) {
	const log: { sent: string[]; updates: IStatementRun[][]; finished: IStatementRun[] } = { sent: [], updates: [], finished: [] };
	let clock = 1000;
	let index = 0;
	const deps: IBatchDeps = {
		run: (prepared) => {
			log.sent.push(prepared.cypher);
			const next = script[index++];
			return next ? next() : Promise.resolve(result(1));
		},
		describe: (error) => (error instanceof Error && error.message === 'stale' ? notice('', true) : notice((error as Error).message)),
		now: () => (clock += 5),
		onUpdate: (runs) => log.updates.push(runs.map((r) => ({ ...r }))),
		onFinished: (run) => log.finished.push(run),
	};
	return { runner: createBatchRunner(deps), log };
}
const last = (log: ReturnType<typeof rig>['log']) => log.updates[log.updates.length - 1];

test('statements run one at a time, in order, each with its own result', async () => {
	let concurrent = 0;
	let peak = 0;
	const step = (n: number) => async () => {
		concurrent += 1;
		peak = Math.max(peak, concurrent);
		await new Promise((r) => setImmediate(r));
		concurrent -= 1;
		return result(n);
	};
	const { runner, log } = rig([step(1), step(2), step(3)]);
	assert.equal(await runner.start(prepare('RETURN 1', 'RETURN 2', 'RETURN 3')), true);
	assert.deepEqual(log.sent, ['RETURN 1', 'RETURN 2', 'RETURN 3']);
	assert.equal(peak, 1, 'one request at a time');
	assert.deepEqual(last(log).map((r) => [r.outcome, r.result?.rows.length]), [['rows', 1], ['rows', 2], ['rows', 3]]);
	assert.equal(log.finished.length, 3);
	assert.equal(runner.running, false);
	assert.equal(formatBatchOutcome(last(log)), 'All 3 statements completed.');
});

test('a failure stops the batch: later statements are skipped and never sent, earlier ones keep their results', async () => {
	const { runner, log } = rig([async () => result(1), async () => result(2), async () => { throw new Error('Query failed'); }, async () => result(4)]);
	await runner.start(prepare('RETURN 1', 'RETURN 2', 'RETURN 3', 'RETURN 4', 'RETURN 5'));
	assert.deepEqual(log.sent, ['RETURN 1', 'RETURN 2', 'RETURN 3'], 'statements 4 and 5 were never sent');
	assert.deepEqual(last(log).map((r) => r.outcome), ['rows', 'rows', 'error', 'skipped', 'skipped']);
	assert.equal(last(log)[2].failure?.headline, 'Query failed');
	assert.equal(last(log)[0].result?.rows.length, 1);
	assert.deepEqual(log.finished.map((r) => r.outcome), ['rows', 'rows', 'error']);
	const text = formatBatchOutcome(last(log));
	assert.match(text, /^Statement 3 failed\./);
	assert.match(text, /Statements 1-2 had already completed on the database: each statement is a separate request, so nothing is rolled back\./);
	assert.match(text, /2 statements were not sent\./);
	assert.ok(!/atomic|transaction|rolled back successfully/i.test(text.replace('nothing is rolled back', '')));
});

test('the wording for one earlier statement and one skipped statement is singular', async () => {
	const { runner, log } = rig([async () => result(1), async () => { throw new Error('x'); }]);
	await runner.start(prepare('RETURN 1', 'RETURN 2', 'RETURN 3'));
	assert.equal(formatBatchOutcome(last(log)), 'Statement 2 failed. Statement 1 had already completed on the database: each statement is a separate request, so nothing is rolled back. Statement 3 was not sent.');
	assert.equal(formatBatchOutcome([{ index: 0, prepared: prepare('RETURN 1')[0], outcome: 'rows' }]), '', 'a successful single statement needs no sentence');
});

test('Stop waiting abandons the statement in flight, skips the rest and ignores the late answer', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { runner, log } = rig([async () => result(1), () => new Promise<ReadQueryResult>((resolve) => { release = resolve; }), async () => result(3)]);
	const done = runner.start(prepare('RETURN 1', 'RETURN 2', 'RETURN 3'));
	await new Promise((r) => setImmediate(r));
	await new Promise((r) => setImmediate(r));
	assert.equal(runner.inFlight, true);
	runner.stopWaiting();
	assert.equal(await done, true);
	assert.deepEqual(last(log).map((r) => r.outcome), ['rows', 'abandoned', 'skipped']);
	assert.deepEqual(log.finished.map((r) => r.outcome), ['rows', 'abandoned']);
	assert.match(formatBatchOutcome(last(log)), /^Stopped waiting at statement 2; the database may still be running it\./);
	// The server finishes the abandoned statement later: nothing changes, nothing is reported.
	const updates = log.updates.length;
	release(result(2));
	await new Promise((r) => setImmediate(r));
	assert.equal(log.updates.length, updates);
	assert.equal(log.sent.length, 2, 'statement 3 was never sent');
	assert.equal(runner.running, false);
});

test('only one batch runs at a time; an empty batch does nothing', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { runner } = rig([() => new Promise<ReadQueryResult>((resolve) => { release = resolve; })]);
	const first = runner.start(prepare('RETURN 1'));
	assert.equal(await runner.start(prepare('RETURN 2')), false, 'refused while running');
	assert.equal(await runner.start([]), false);
	release(result(1));
	await first;
	assert.equal(runner.running, false);
	assert.equal(await runner.start([]), false);
	assert.equal(runner.running, false);
});

test('a stale failure is dropped quietly: no error is shown and the rest is not sent', async () => {
	const { runner, log } = rig([async () => { throw new Error('stale'); }]);
	await runner.start(prepare('RETURN 1', 'RETURN 2'));
	assert.deepEqual(log.sent, ['RETURN 1']);
	assert.equal(log.finished.length, 0, 'nothing is recorded in history for a dropped result');
	assert.deepEqual(last(log).map((r) => r.outcome), ['skipped', 'skipped']);
});

test('round-trip time is measured per statement', async () => {
	const { runner, log } = rig([async () => result(1)]);
	await runner.start(prepare('RETURN 1'));
	assert.ok((log.finished[0].ms ?? 0) > 0);
	assert.ok(log.finished[0].startedAt !== undefined);
});

test('the running line names the statement being sent', async () => {
	let release: (r: ReadQueryResult) => void = () => undefined;
	const { runner, log } = rig([async () => result(1), () => new Promise<ReadQueryResult>((resolve) => { release = resolve; })]);
	const done = runner.start(prepare('RETURN 1', 'RETURN 2'));
	await new Promise((r) => setImmediate(r));
	await new Promise((r) => setImmediate(r));
	assert.equal(formatBatchOutcome(last(log)), 'Running statement 2 of 2.');
	release(result(2));
	await done;
});
