// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// RUN SURFACE HELPERS: the editor request mailbox
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createLoadSlot } from '../src/graph/loadSlot';

// GX-FE-03: the request was kept in the host's state and the surface de-duplicated it with a ref that starts at 0 on
// every mount, so any remount replayed it: the editor text and its saved draft were overwritten, and a preview
// (or a History "Run again") ran again by itself.
test('a request left for the editor is taken exactly once: a remount finds nothing to replay', () => {
	const slot = createLoadSlot();
	assert.equal(slot.take(), null, 'nothing before anything is put');
	const seq = slot.put({ text: 'MATCH (n:Person) RETURN n LIMIT 25', run: true });
	assert.equal(seq, 1);
	assert.deepEqual(slot.take(), { text: 'MATCH (n:Person) RETURN n LIMIT 25', run: true });
	assert.equal(slot.take(), null, 'a second mount takes nothing');
	assert.equal(slot.take(), null);
});

test('a newer request replaces one not yet taken, and every put has a new sequence number', () => {
	const slot = createLoadSlot();
	assert.equal(slot.put({ text: 'old', run: true }), 1);
	assert.equal(slot.put({ text: 'new', run: false }), 2);
	assert.deepEqual(slot.take(), { text: 'new', run: false });
	assert.equal(slot.take(), null);
	assert.equal(slot.put({ text: 'again', run: false }), 3);
	assert.deepEqual(slot.take(), { text: 'again', run: false });
});
