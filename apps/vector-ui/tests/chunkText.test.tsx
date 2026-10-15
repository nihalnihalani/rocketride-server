// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// CHUNK TEXT: the selected chunk's full text in the point inspector
// =============================================================================
//
// The inspector holds the ChunkTextPanel for the selected point. A component
// still a placeholder says "Not built yet".
// =============================================================================

import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PointInspector } from '../src/components/PointInspector';
import { loadSample, modelOf } from './support/map.samples';

const noop = (): void => undefined;

test('the inspector of a selected point holds its ChunkTextPanel; with nothing selected there is none', () => {
	const sample = modelOf(loadSample('sample_demo_1000.json'));
	const props = { sample, neighbours: null, querySim: null, writes: { enabled: true, reason: null }, onOpenDocument: noop, onFindSimilar: noop, onRemoveDocument: noop };
	const html = renderToStaticMarkup(<PointInspector {...props} index={0} />);
	const at = html.search(/<[a-z]+[^>]*data-component="ChunkTextPanel"/);
	assert.ok(at >= 0, 'the panel is mounted for the selected point');
	if (html.slice(at, html.indexOf('>', at)).includes('data-placeholder')) assert.match(html.slice(at, at + 600), /Not built yet/);
	assert.doesNotMatch(renderToStaticMarkup(<PointInspector {...props} index={null} />), /data-component="ChunkTextPanel"/);
});
