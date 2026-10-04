// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// FAILURE NOTICES AND RUN CONFIGURATION
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatBatchOutcome, formatPriorStatements } from 'shared/explorer';
import type { IStatementRunBase } from 'shared/explorer';
import { ExplorerToolError } from 'shared/explorer';
import { describeFailure, describeFailureMessage, describeFailureOf } from '../src/graph/failures';
import type { IFailureInput } from '../src/graph/failures';
import { GRAPH_BATCH_WORDS, prepareStatement, refuseNonReads, toHistoryEntry } from '../src/graph/runConfig';
import { parseDialect } from '../src/graph/dialect';
import { fixture } from './support/builders';

const errors = fixture<Record<string, string>>('errors');

/** A failure input the way the shared session builds it from a verbatim message. */
function failure(kind: string, message: string, tool = 'read_query'): IFailureInput {
	const at = message.indexOf('\n');
	return { kind, tool, message, headline: at === -1 ? message : message.slice(0, at), ...(at === -1 ? {} : { detail: message.slice(at + 1) }) };
}

test('a refusal leads with the node\'s headline, the database text under it, and points at the write console only where there is one', () => {
	const read = describeFailure(failure('raised', errors.refused_write), false);
	assert.equal(read.headline, 'Refused: read_query is read-only; this statement writes (CREATE)');
	assert.match(read.detail, /Use the write console/);
	assert.match(read.hint ?? '', /Browsing is read-only/);
	const writable = describeFailure(failure('raised', errors.refused_write), true);
	assert.match(writable.hint ?? '', /use the write console for this connection/);
	assert.equal(read.ignore, false);
});

test('an AGE limitation keeps the node\'s explanation and says what to do', () => {
	const n = describeFailure(failure('raised', errors.age_hint), false);
	assert.match(n.headline, /^Not supported on Apache AGE 1\.5\.0: date\(\)/);
	assert.match(n.detail, /store dates as ISO-8601 strings/);
	assert.match(n.hint ?? '', /rewrite the query/);
});

test('a timeout says this app stopped waiting and that nothing here cancels the query', () => {
	const n = describeFailure(failure('timeout', 'Stopped waiting for read_query after 40 s. The node may still be running it; there is no way to cancel it from here.'), false);
	assert.equal(n.variant, 'warning');
	assert.match(n.hint ?? '', /cannot be cancelled from here/);
	const node = describeFailure(failure('raised', errors.timeout), false);
	assert.match(node.headline, /^Query timed out after 30000 ms/);
	assert.match(node.hint ?? '', /Narrow it, or lower the row limit/);
});

test('an upgrade (and the engine\'s unknown-tool text) is a warning with the upgrade message, never a fallback hint', () => {
	for (const input of [failure('upgrade', 'This node does not advertise read_query'), failure('raised', 'No handler found for tool read_query')]) {
		const n = describeFailure(input, true);
		assert.equal(n.variant, 'warning');
		assert.match(n.headline, /does not support read_query yet/);
		assert.match(n.headline, /never falls back to execute/);
	}
});

test('the legacy execute-disabled text is recognised', () => {
	const n = describeFailure(failure('raised', errors.execute_disabled_legacy, 'execute'), false);
	assert.equal(n.headline, 'This node does not allow execute (allow_execute is off).');
	assert.match(n.hint ?? '', /Browsing with Cypher works/);
});

test('unavailable, malformed and invalid failures each get their own plain hint', () => {
	assert.match(describeFailure(failure('unavailable', "No running task for pipeline 'P'. Start the pipeline and retry."), false).hint ?? '', /Start the pipeline/);
	assert.match(describeFailure(failure('malformed', 'read_query returned a malformed result: columns is not an array'), false).hint ?? '', /may need an upgrade/);
	assert.equal(describeFailure(failure('invalid', 'Generated query contains write or admin clauses', 'get_query'), false).variant, 'error');
	assert.match(describeFailure(failure('raised', errors.invalid_input), false).headline, /^Invalid read_query input/);
});

test('a stale result is ignored entirely', () => {
	const n = describeFailure(failure('stale', 'superseded'), false);
	assert.equal(n.ignore, true);
	assert.equal(n.headline, '');
});

test('an unrecognised failure shows the node\'s text unchanged', () => {
	const n = describeFailure(failure('raised', errors.db_error), false);
	assert.equal(n.headline, 'Query failed');
	assert.match(n.detail, /^Database said: Variable `x` not defined/);
	assert.equal(n.hint, null);
	assert.equal(describeFailure({ kind: 'raised', tool: 't', message: '', headline: '' }, false).headline, '');
});

// -----------------------------------------------------------------------------
// Run configuration
// -----------------------------------------------------------------------------

const neo = parseDialect(fixture<Record<string, unknown>>('dialect_neo4j'));

test('a statement is sent exactly as written (a trailing semicolon removed), and the limit travels separately', () => {
	const p = prepareStatement('  MATCH (n) RETURN n;  ', 1000, neo);
	assert.equal(p.cypher, 'MATCH (n) RETURN n');
	assert.equal(p.limit, 1000);
	assert.equal(p.kind, 'read');
	assert.ok(!/limit/i.test(p.cypher), 'no LIMIT was added to the user\'s text');
	assert.equal(prepareStatement('RETURN 1;;', null, neo).limit, 25000, 'All is the node cap');
	assert.equal(prepareStatement('RETURN 1', 1000, null).limit, 1000);
	const comment = prepareStatement('MATCH (n) RETURN n // see ;', 200, neo);
	assert.equal(comment.cypher, 'MATCH (n) RETURN n // see ;', 'a semicolon inside a comment is not stripped');
});

test('writes are recognised with their finding; reads have none', () => {
	assert.equal(prepareStatement('CREATE (n)', 200, neo).kind, 'write');
	assert.equal(prepareStatement('CREATE (n)', 200, neo).finding?.kind, 'CREATE');
	assert.equal(prepareStatement('MATCH (n) RETURN n', 200, neo).finding, null);
});

test('the browse editor refuses a batch holding a write and names which statement and what was seen', () => {
	const batch = ['MATCH (n) RETURN n', 'MATCH (n) DETACH DELETE n', 'RETURN 1'].map((s) => prepareStatement(s, 1000, neo));
	const refusal = refuseNonReads(batch, false);
	assert.match(refusal ?? '', /^This editor only reads\. Statement 2 looks like it changes data or runs a command \(DETACH DELETE\)\./);
	assert.match(refusal ?? '', /no write console/);
	assert.match(refuseNonReads(batch, true) ?? '', /Use the write console for this connection\./);
	assert.match(refusal ?? '', /This is a text check, not a database safeguard\.$/);
	assert.equal(refuseNonReads(['RETURN 1', 'MATCH (n) RETURN n'].map((s) => prepareStatement(s, 1000, neo)), false), null);
});

test('a history entry holds the statement and the run, and nothing else', () => {
	const entry = toHistoryEntry({ cypher: 'MATCH (n) RETURN n', at: 5, ms: 12.6, outcome: 'rows', rows: 3, limit: 1000, kind: 'MATCH' }, 'id-1');
	assert.deepEqual(entry, { id: 'id-1', at: 5, ms: 13, outcome: 'rows', rows: 3, limit: 1000, kind: 'MATCH', cypher: 'MATCH (n) RETURN n' });
	const failed = toHistoryEntry({ cypher: 'X', at: 1, ms: -3, outcome: 'error', error: 'boom', kind: '' }, 'id-2');
	assert.equal(failed.ms, 0);
	assert.equal(failed.kind, 'OTHER');
	assert.equal(failed.error, 'boom');
	assert.ok(!('rows' in failed));
	assert.ok(!JSON.stringify(entry).includes('token'));
});

test('the shared runner hands over the message only: the kinds the session writes are recognised by their fixed wording', () => {
	assert.equal(describeFailureMessage('Stopped waiting for read_query after 40 s. The node may still be running it; there is no way to cancel it from here.', false).variant, 'warning');
	assert.match(describeFailureMessage('This node cannot run read_query: it does not advertise "read_query". Update the pipeline\'s node to a version that supports it.', true).headline, /does not support read_query yet/);
	assert.match(describeFailureMessage("No running task for pipeline 'P'. Start the pipeline and retry.", false).hint ?? '', /Start the pipeline/);
	assert.match(describeFailureMessage('read_query returned a malformed result: columns is not an array', false).hint ?? '', /may need an upgrade/);
	const refused = describeFailureMessage(errors.refused_write, false);
	assert.equal(refused.headline, 'Refused: read_query is read-only; this statement writes (CREATE)');
	assert.equal(refused.verbatim, 'Use the write console (execute) on a node with allow_execute enabled.', 'the node\'s remaining lines are the verbatim "Database said" text');
	assert.equal(refused.generic, false);
	const plain = describeFailureMessage('Something odd', false);
	assert.equal(plain.headline, 'Something odd');
	assert.equal(plain.verbatim, '');
	// A node message that merely mentions these words is not mistaken for a session message.
	assert.equal(describeFailureMessage('Query failed\nDatabase said: Stopped waiting for lock after 3 s.', false).variant, 'error');
});

test('Graph\'s batch words never claim a rollback and name nothing as committed', () => {
	const run = (index: number, kind: string, outcome: IStatementRunBase['outcome']): IStatementRunBase => ({ index, kind, verb: kind.toUpperCase(), outcome });
	const reads = [run(0, 'read', 'rows'), run(1, 'read', 'rows'), run(2, 'read', 'error')];
	assert.equal(formatPriorStatements(reads, 2, GRAPH_BATCH_WORDS), 'Statements 1\u20132 already ran.');
	const writes = [run(0, 'write', 'rows'), run(1, 'read', 'error')];
	assert.equal(formatPriorStatements(writes, 1, GRAPH_BATCH_WORDS), 'Statement 1 already executed on the database: each statement is a separate request, so nothing is rolled back.');
	assert.equal(formatBatchOutcome([run(0, 'read', 'rows'), run(1, 'write', 'rows'), run(2, 'write', 'error'), run(3, 'write', 'skipped')], GRAPH_BATCH_WORDS), '1 ran \u00b7 2 executed \u00b7 3 failed \u00b7 4 not run');
	for (const text of [GRAPH_BATCH_WORDS.changed, GRAPH_BATCH_WORDS.priorChanged('x'), GRAPH_BATCH_WORDS.priorRead('x')]) assert.ok(!/committed|atomic|transaction/i.test(text.replace('nothing is rolled back', '')), text);
});

test('when the shared runner passes the thrown ExplorerToolError, its kind decides, not the wording', () => {
	const timeout = new ExplorerToolError({ kind: 'timeout', tool: 'read_query', message: 'Anything at all, worded differently' });
	assert.equal(describeFailureOf(timeout.message, timeout, false).variant, 'warning');
	const upgrade = new ExplorerToolError({ kind: 'upgrade', tool: 'read_query', message: 'Totally different words' });
	assert.match(describeFailureOf(upgrade.message, upgrade, true).headline, /does not support read_query yet/);
	const refused = new ExplorerToolError({ kind: 'raised', tool: 'read_query', message: errors.refused_call });
	const notice = describeFailureOf(refused.message, refused, false);
	assert.match(notice.headline, /^Refused: CALL apoc\.periodic\.iterate/);
	assert.match(notice.verbatim, /^Allowed: db\.labels/);
	// A plain Error (or nothing) falls back to reading the message.
	assert.equal(describeFailureOf('boom', new Error('boom'), false).headline, 'boom');
	assert.equal(describeFailureOf('boom', undefined, false).headline, 'boom');
});
