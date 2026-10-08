// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// OBJECT IDS WITHOUT crypto.subtle (grep-pinned)
// =============================================================================
//
// The app derives a dropped file's objectId (uuid5 of 'null://Stream/' +
// path) to ask whether the path is already stored. `crypto.subtle` exists
// only in secure contexts: on a LAN origin (http://<host-ip>) it is undefined,
// and the check would throw there. So the derivation is pure JavaScript
// (vector/sha1.ts) and no source file may reach for `crypto.subtle`. The
// derivation's own vectors are pinned by its lane's tests.
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const SRC = path.resolve(__dirname, '..', 'src');

/** Every source file of the app. */
function sources(dir: string = SRC): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? sources(path.join(dir, entry.name)) : /\.(ts|tsx)$/.test(entry.name) ? [path.join(dir, entry.name)] : []));
}

test('no source file uses crypto.subtle (undefined on a LAN origin)', () => {
	const files = sources();
	assert.ok(files.length > 30, "the premise: the app's sources were read");
	for (const file of files) {
		const text = fs.readFileSync(file, 'utf8');
		assert.doesNotMatch(text, /crypto\s*\.\s*subtle|\bsubtle\s*\.\s*digest|window\.crypto|globalThis\.crypto/, `${path.relative(SRC, file)} reaches for the Web Crypto API`);
	}
});

test('the objectId derivation is pure JavaScript over vector/sha1.ts', (t) => {
	const objectId = path.join(SRC, 'vector', 'objectId.ts');
	if (!fs.existsSync(objectId)) {
		t.skip('NEEDS:L9 merged — integration gate G2 (vector/objectId.ts and vector/sha1.ts are on the chat and ingest lane)');
		return;
	}
	assert.match(fs.readFileSync(objectId, 'utf8'), /from '\.\/sha1'/);
	assert.ok(fs.existsSync(path.join(SRC, 'vector', 'sha1.ts')));
});
