// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// INGEST SUMMARY: the summary of a drop, above its upload rows
// =============================================================================
//
// The upload list holds the drop's summary (IngestSummary) above its rows
// while there are rows. A part still a placeholder says "Not built yet".
// =============================================================================

import assert from 'node:assert/strict';
import Module from 'node:module';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { UploadRow } from '../src/vector/uploads';

// The shell's style fragments exist only inside a running shell.
const shellStandIn = { commonStyles: new Proxy({}, { get: () => ({}) }) };
const moduleWithLoad = Module as unknown as { _load: (request: string, parent: unknown, isMain: boolean) => unknown };
const originalLoad = moduleWithLoad._load;
moduleWithLoad._load = function (request: string, parent: unknown, isMain: boolean): unknown {
	if (request === 'shell') return shellStandIn;
	return originalLoad.call(this, request, parent, isMain);
};

const { UploadList } = require('../src/components/UploadList') as typeof import('../src/components/UploadList');

test('the upload list holds the drop summary above its rows, and renders nothing without rows', () => {
	const row: UploadRow = { id: 'u1', path: 'docs/a.md', name: 'a.md', objectId: 'o', size: 100, status: 'done', bytesSent: 100, fileSize: 100, chunks: 7, existingChunks: null, message: null, detail: null };
	const html = renderToStaticMarkup(React.createElement(UploadList, { rows: [row], notes: [], onClearFinished: () => undefined }));
	const at = html.search(/<[a-z]+[^>]*data-component="IngestSummary"/);
	assert.ok(at >= 0, 'the summary is mounted');
	assert.ok(at < html.indexOf('aria-label="Uploads"'), 'above the rows');
	if (html.slice(at, html.indexOf('>', at)).includes('data-placeholder')) assert.match(html.slice(at, at + 600), /Not built yet/);
	assert.equal(renderToStaticMarkup(React.createElement(UploadList, { rows: [], notes: [], onClearFinished: () => undefined })), '');
});
