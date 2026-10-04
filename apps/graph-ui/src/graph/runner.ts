// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// =============================================================================
// GRAPH - SEQUENTIAL STATEMENT RUNNER (stop on failure, per-statement results)
// =============================================================================
//
// Runs the statements of a buffer ONE AT A TIME, in order, each as its own call:
//
//   - A failure STOPS the batch. The failed statement keeps its error, every later
//     statement is marked `skipped` (never sent), and every earlier statement keeps
//     its own result.
//   - Statements are separate requests, so NOTHING IS ATOMIC: the wording never
//     says a batch was rolled back, and a batch that failed at statement 3 says
//     that statements 1 and 2 had already run.
//   - Stop waiting stops THIS runner at once: the statement in flight becomes
//     `abandoned` (the database may still be running it and cannot be told to
//     stop), the rest are `skipped`, and the late answer of the abandoned call is
//     ignored.
//   - One batch at a time: starting a second while one runs is refused.
//   - A result belongs to the run that asked for it: after Stop waiting, or when a
//     newer run replaced it, a late answer is dropped without a trace.
//
// The runner knows nothing about the transport. It is given `run`, which sends one
// prepared statement and resolves with the node's answer (or throws), and it
// reports through callbacks; the workbench wires those to the tool session, the
// history store and the live region.
// =============================================================================

import type { IFailureNotice } from './failures';
import type { IPreparedStatement } from './runConfig';
import type { ReadQueryResult } from './types';

// =============================================================================
// TYPES
// =============================================================================

/** How one statement of a batch ended. */
export type RunOutcome = 'pending' | 'running' | 'rows' | 'error' | 'abandoned' | 'skipped';

/** One statement of a batch, with whatever is known about it so far. */
export interface IStatementRun {
	/** Zero-based position in the batch. */
	index: number;
	prepared: IPreparedStatement;
	outcome: RunOutcome;
	/** The node's answer, when the outcome is `rows`. */
	result?: ReadQueryResult;
	/** Why it failed, when the outcome is `error`. */
	failure?: IFailureNotice;
	/** Epoch ms when it was sent. */
	startedAt?: number;
	/** Round-trip milliseconds. */
	ms?: number;
}

/** What the runner is given. */
export interface IBatchDeps {
	/** Send one prepared statement. May throw (the error is described by `describe`). */
	run(prepared: IPreparedStatement, index: number): Promise<ReadQueryResult>;
	/** Turn a thrown error into a notice; a notice with `ignore` set drops the result silently. */
	describe(error: unknown): IFailureNotice;
	/** The clock. */
	now(): number;
	/** Told after every change to the batch. */
	onUpdate(runs: readonly IStatementRun[]): void;
	/** Told once per statement that finished (rows, error or abandoned): history records it. */
	onFinished(run: IStatementRun): void;
}

/** A batch runner. */
export interface IBatchRunner {
	/** Run the statements in order. Resolves when the batch ended (or was stopped). Refused (resolves false) while a batch runs. */
	start(statements: readonly IPreparedStatement[]): Promise<boolean>;
	/** Stop waiting for the batch. No-op when none runs. */
	stopWaiting(): void;
	/** True while a batch runs. */
	readonly running: boolean;
	/** True while a statement has been sent and has not answered. */
	readonly inFlight: boolean;
}

// =============================================================================
// RUNNER
// =============================================================================

/**
 * Create a batch runner.
 *
 * @param deps - Transport, description, clock and callbacks.
 * @returns The runner.
 */
export function createBatchRunner(deps: IBatchDeps): IBatchRunner {
	let generation = 0;
	let running = false;
	let inFlight = false;
	let stopSignal: (() => void) | null = null;

	return {
		get running() {
			return running;
		},
		get inFlight() {
			return inFlight;
		},

		stopWaiting(): void {
			if (!running) return;
			stopSignal?.();
		},

		async start(statements: readonly IPreparedStatement[]): Promise<boolean> {
			if (running || statements.length === 0) return false;
			running = true;
			const mine = ++generation;
			const runs: IStatementRun[] = statements.map((prepared, index) => ({ index, prepared, outcome: 'pending' }));
			const publish = (): void => deps.onUpdate(runs.map((r) => ({ ...r })));
			publish();

			// One promise settles when the user stops waiting; it is raced against each call.
			const stopped = new Promise<'stopped'>((resolve) => {
				stopSignal = () => resolve('stopped');
			});

			try {
				for (let i = 0; i < runs.length; i++) {
					const run = runs[i];
					run.outcome = 'running';
					run.startedAt = deps.now();
					inFlight = true;
					publish();

					let answer: ReadQueryResult | 'stopped';
					let thrown: unknown;
					let failed = false;
					try {
						answer = await Promise.race([deps.run(run.prepared, i), stopped]);
					} catch (error) {
						failed = true;
						thrown = error;
						answer = 'stopped';
					}
					inFlight = false;
					run.ms = deps.now() - (run.startedAt ?? deps.now());

					if (generation !== mine) return true; // superseded: nothing may be reported

					if (answer === 'stopped' && !failed) {
						// The user stopped waiting. The call may still finish on the server; its answer is never shown.
						run.outcome = 'abandoned';
						for (let j = i + 1; j < runs.length; j++) runs[j].outcome = 'skipped';
						publish();
						deps.onFinished({ ...run });
						return true;
					}
					if (failed) {
						const notice = deps.describe(thrown);
						if (notice.ignore) {
							// A stale result: drop it quietly and end the batch without a trace of this statement.
							for (let j = i; j < runs.length; j++) runs[j].outcome = 'skipped';
							publish();
							return true;
						}
						run.outcome = 'error';
						run.failure = notice;
						for (let j = i + 1; j < runs.length; j++) runs[j].outcome = 'skipped';
						publish();
						deps.onFinished({ ...run });
						return true;
					}
					run.outcome = 'rows';
					run.result = answer as ReadQueryResult;
					publish();
					deps.onFinished({ ...run });
				}
				return true;
			} finally {
				if (generation === mine) {
					running = false;
					inFlight = false;
					stopSignal = null;
				}
			}
		},
	};
}

// =============================================================================
// WORDING
// =============================================================================

/**
 * The batch's outcome in one sentence, without ever claiming atomicity.
 *
 * @param runs - The batch's statements.
 * @returns Text for the status line; '' for a one-statement batch that succeeded.
 */
export function formatBatchOutcome(runs: readonly IStatementRun[]): string {
	if (runs.length <= 1) {
		const only = runs[0];
		if (!only || only.outcome === 'rows' || only.outcome === 'pending' || only.outcome === 'running') return '';
	}
	const ran = runs.filter((r) => r.outcome === 'rows').length;
	const failed = runs.find((r) => r.outcome === 'error');
	const abandoned = runs.find((r) => r.outcome === 'abandoned');
	const skipped = runs.filter((r) => r.outcome === 'skipped').length;
	if (runs.some((r) => r.outcome === 'running' || r.outcome === 'pending')) return `Running statement ${runs.findIndex((r) => r.outcome === 'running' || r.outcome === 'pending') + 1} of ${runs.length}.`;
	const parts: string[] = [];
	if (failed) parts.push(`Statement ${failed.index + 1} failed.`);
	else if (abandoned) parts.push(`Stopped waiting at statement ${abandoned.index + 1}; the database may still be running it.`);
	else return `All ${runs.length} statements completed.`;
	if (ran > 0) parts.push(`${ran === 1 ? 'Statement 1 had' : `Statements 1-${ran} had`} already completed on the database: each statement is a separate request, so nothing is rolled back.`);
	if (skipped > 0) parts.push(`${skipped === 1 ? `Statement ${runs.findIndex((r) => r.outcome === 'skipped') + 1} was` : `${skipped} statements were`} not sent.`);
	return parts.join(' ');
}
