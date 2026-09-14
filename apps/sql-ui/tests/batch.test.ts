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
// SQL BATCH — unit tests for the multi-statement outcome wording
// =============================================================================
//
// The summary line is the app's one chance to say that a failed batch left
// earlier statements COMMITTED, so its grouping is pinned here.
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { IStatementRun, RunOutcome } from '../src/sql/batch';
import { formatBatchOutcome, formatElapsed, formatRunLabel, leadingVerb } from '../src/sql/batch';

/**
 * Build a batch from a list of outcomes.
 *
 * @param outcomes - One outcome per statement, in order.
 * @returns The statement runs.
 */
function batch(outcomes: RunOutcome[]): IStatementRun[] {
	return outcomes.map((outcome, index) => ({
		index,
		sql: 'SELECT 1',
		kind: 'read' as const,
		verb: 'SELECT',
		startLine: index + 1,
		endLine: index + 1,
		outcome,
	}));
}

describe('leadingVerb', () => {
	it('reads the first keyword', () => {
		assert.equal(leadingVerb('select * from t'), 'SELECT');
	});

	it('skips a leading comment', () => {
		assert.equal(leadingVerb('-- note\nUPDATE t SET a = 1'), 'UPDATE');
	});

	it('skips a leading parenthesis', () => {
		assert.equal(leadingVerb('(SELECT 1) UNION (SELECT 2)'), 'SELECT');
	});

	it('falls back when there is no keyword', () => {
		assert.equal(leadingVerb('   '), 'SQL');
	});
});

describe('formatElapsed', () => {
	it('reports milliseconds as seconds, never as query time', () => {
		assert.equal(formatElapsed(31.4), 'round trip 0.031 s');
	});
});

describe('formatBatchOutcome', () => {
	it('produces the bound wording for a partly failed batch', () => {
		const runs = batch(['rows', 'affected', 'error', 'skipped', 'skipped']);
		assert.equal(formatBatchOutcome(runs), '1–2 committed · 3 failed · 4–5 not run');
	});

	it('collapses one statement to a single number', () => {
		assert.equal(formatBatchOutcome(batch(['error'])), '1 failed');
	});

	it('reports a fully successful batch', () => {
		assert.equal(formatBatchOutcome(batch(['rows', 'rows', 'affected'])), '1–3 committed');
	});

	it('reports an abandoned statement separately', () => {
		assert.equal(formatBatchOutcome(batch(['rows', 'abandoned', 'skipped'])), '1 committed · 2 abandoned · 3 not run');
	});

	it('leaves a running statement out of the line', () => {
		assert.equal(formatBatchOutcome(batch(['rows', 'running', 'pending'])), '1 committed · 3 not run');
	});

	it('says nothing about an empty batch', () => {
		assert.equal(formatBatchOutcome([]), '');
	});
});

describe('formatRunLabel', () => {
	it('labels a row result', () => {
		const [run] = batch(['rows']);
		assert.equal(formatRunLabel({ ...run, rows: [{}, {}], ms: 31 }), '1 SELECT · 2 rows · round trip 0.031 s');
	});

	it('labels an affected-row result', () => {
		const [run] = batch(['affected']);
		assert.equal(formatRunLabel({ ...run, verb: 'UPDATE', affected: 3, ms: 12 }), '1 UPDATE · 3 affected · round trip 0.012 s');
	});

	it('labels a failure', () => {
		assert.equal(formatRunLabel(batch(['error'])[0]), '1 SELECT · error');
	});

	it('labels a skipped statement', () => {
		assert.equal(formatRunLabel(batch(['skipped'])[0]), '1 SELECT · not run');
	});

	it('labels a running statement', () => {
		assert.equal(formatRunLabel(batch(['running'])[0]), '1 SELECT · running…');
	});

	it('labels an abandoned statement', () => {
		const [run] = batch(['abandoned']);
		assert.equal(formatRunLabel({ ...run, ms: 1200 }), '1 SELECT · abandoned · round trip 1.200 s');
	});
});
