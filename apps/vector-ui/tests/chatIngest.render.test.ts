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
// chatIngest.render — what the chat and ingest panels put on screen
// =============================================================================
//
// Server-rendered smoke tests (there is no DOM harness): each panel renders
// its available and unavailable states with the right sentences, accessible
// names and controls. The shell's components are replaced by plain stand-ins
// that render their text, loaded before the panels are.
// =============================================================================

import { test as nodeTest } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { IExplorerEndpoint, IRoleChannel } from 'shared/explorer';
import type { ConsoleActions, ConsoleModel, IChatSource, IDialectResult, VectorChannels } from '../src/contract/types';
import { createSelectionStore } from '../src/contract/bridge';
import type { UploadRow } from '../src/vector/uploads';

/** Most a test here may take: they await fakes, so a regression must fail, not hang the run. */
const TEST_TIMEOUT_MS = 10_000;

/**
 * Declare a test bounded by {@link TEST_TIMEOUT_MS}.
 *
 * @param name - What it checks.
 * @param fn - The test.
 */
function test(name: string, fn: () => void | Promise<void>): void {
	void nodeTest(name, { timeout: TEST_TIMEOUT_MS }, fn);
}

// ── Shell stand-ins (installed before any panel module loads) ────────────────

const h = React.createElement;
const shellStandIn = {
	commonStyles: new Proxy({}, { get: () => ({}) }),
	EmptyState: ({ title, description }: { title: string; description?: string }) => h('div', { 'data-empty-state': '' }, h('strong', null, title), description ? h('p', null, description) : null),
	Banner: ({ variant, children }: { variant: string; children: React.ReactNode }) => h('div', { 'data-banner': variant }, children),
	ConfirmDialog: (props: { title: string; message: React.ReactNode; confirmLabel?: string; cancelLabel?: string }) => h('div', { role: 'dialog', 'aria-label': props.title }, props.message, h('button', null, props.cancelLabel ?? 'Cancel'), h('button', null, props.confirmLabel ?? 'Save')),
	useShellEvent: () => undefined,
};
const moduleWithLoad = Module as unknown as { _load: (request: string, parent: unknown, isMain: boolean) => unknown };
const originalLoad = moduleWithLoad._load;
moduleWithLoad._load = function (request: string, parent: unknown, isMain: boolean): unknown {
	if (request === 'shell') return shellStandIn;
	return originalLoad.call(this, request, parent, isMain);
};

const { IngestPanel, NO_INGEST_SENTENCE } = require('../src/components/IngestPanel') as typeof import('../src/components/IngestPanel');
const { ChatPanel, NO_CHAT_SENTENCE } = require('../src/components/ChatPanel') as typeof import('../src/components/ChatPanel');
const { SourcesPanel } = require('../src/components/SourcesPanel') as typeof import('../src/components/SourcesPanel');
const { RetrievalDebugger } = require('../src/components/RetrievalDebugger') as typeof import('../src/components/RetrievalDebugger');
const { ScoreHistogram } = require('../src/components/ScoreHistogram') as typeof import('../src/components/ScoreHistogram');
const { UploadList } = require('../src/components/UploadList') as typeof import('../src/components/UploadList');
const { IngestDropZone } = require('../src/components/IngestDropZone') as typeof import('../src/components/IngestDropZone');
const { ReplaceConfirmDialog } = require('../src/ingest/ReplaceConfirmDialog') as typeof import('../src/ingest/ReplaceConfirmDialog');
const { chatSessionFor, forgetChatAndIngest } = require('../src/chat/registry') as typeof import('../src/chat/registry');
const { parseChatResult } = require('../src/vector/chatResult') as typeof import('../src/vector/chatResult');
const { replaceQuestion } = require('../src/vector/uploads') as typeof import('../src/vector/uploads');

// ── Fixtures ────────────────────────────────────────────────────────────────

/**
 * Read a provisional fixture.
 *
 * @param name - File name.
 * @returns The parsed JSON.
 */
function fixture<T>(name: string): T {
	return JSON.parse(readFileSync(path.join(__dirname, 'fixtures', 'provisional', name), 'utf8')) as T;
}

const dialect = fixture<IDialectResult>('dialect_pgvector.json');
const chatAnswer = fixture<Record<string, unknown>>('chat_result_with_documents.json');

/**
 * A console model for one connection.
 *
 * @param overrides - Fields to replace.
 * @returns The model.
 */
function model(overrides: Partial<ConsoleModel> = {}): ConsoleModel {
	return {
		connectionKey: 'render-1',
		connection: { endpoint: { key: 'render-1', anchorRole: 'tools', readOnly: false, nodeId: 'store_1', pipelineName: 'Vector demo' } as unknown as IExplorerEndpoint, dialect },
		nodes: { store: 'store_1', embed: 'embed_1', llm: 'llm_1', llmName: 'Local stub LLM' },
		collection: 'vx_demo_docs',
		stats: null,
		limits: dialect.limits,
		capabilities: dialect.capabilities,
		writes: { enabled: true, reason: null },
		ingest: { enabled: true, reason: null },
		chat: { enabled: true, reason: null },
		embed: { enabled: true, reason: null },
		readOnly: false,
		...overrides,
	};
}

/**
 * A channel that answers nothing (rendering never calls it).
 *
 * @param role - The role.
 * @returns The channel.
 */
function idleChannel(role: string): IRoleChannel {
	return { role, bound: true, sendFiles: async () => [], ask: async () => ({}), invoke: async <T>() => ({}) as T };
}

const channels: VectorChannels = { tools: idleChannel('tools'), chat: idleChannel('chat'), ingest: idleChannel('ingest') };

/** Actions that record nothing (rendering never calls them). */
const actions: ConsoleActions = {
	openDocument: () => undefined,
	showOnMap: () => undefined,
	requestRemove: () => undefined,
	askAbout: () => undefined,
	documentsChanged: () => undefined,
	announce: () => undefined,
};

/**
 * Render an element to static markup.
 *
 * @param element - The element.
 * @returns The markup.
 */
function render(element: React.ReactElement): string {
	return renderToStaticMarkup(element);
}

// ── Ingest ──────────────────────────────────────────────────────────────────

test('IngestPanel: the drop zone names the collection, offers files and folders, and the prefix box', () => {
	forgetChatAndIngest();
	const html = render(h(IngestPanel, { model: model(), channels, actions, alsoReaches: [] }));
	assert.match(html, /Drop files or folders here to add them to vx_demo_docs/);
	assert.match(html, /PDF, DOCX, PPTX, XLSX, ODT, RTF, TXT, MD, CSV, HTML, JSON · up to 20 files · 50 MB each/);
	assert.match(html, /<input[^>]*type="file"[^>]*multiple=""[^>]*accept="\.pdf,\.docx/);
	assert.match(html, /<input[^>]*aria-label="Choose a folder to add to vx_demo_docs"[^>]*webkitdirectory=""/);
	assert.match(html, />Add files</);
	assert.match(html, />Add folder</);
	assert.match(html, /Store under folder/);
	assert.doesNotMatch(html, /also reaches/);
	forgetChatAndIngest();
});

test('IngestPanel: names the other stores the ingest source feeds', () => {
	forgetChatAndIngest();
	const html = render(h(IngestPanel, { model: model(), channels, actions, alsoReaches: ['Archive store'] }));
	assert.match(html, /This pipeline&#x27;s ingest also reaches: Archive store/);
	forgetChatAndIngest();
});

test('IngestPanel: without an Ingest source, or on a read-only connection, it says why', () => {
	forgetChatAndIngest();
	const none = render(h(IngestPanel, { model: model(), channels: { ...channels, ingest: null }, actions, alsoReaches: [] }));
	assert.match(none, /Adding documents is not available/);
	assert.ok(none.includes(NO_INGEST_SENTENCE.replace(/'/g, '&#x27;')));
	assert.doesNotMatch(none, /type="file"/);
	const readOnly = render(h(IngestPanel, { model: model({ readOnly: true, ingest: { enabled: false, reason: 'No Tools source: documents cannot be added or removed from here' } }), channels, actions, alsoReaches: [] }));
	assert.match(readOnly, /No Tools source: documents cannot be added or removed from here/);
	forgetChatAndIngest();
});

test('IngestDropZone: disabled shows the reason and disables both pickers', () => {
	const html = render(h(IngestDropZone, { collection: 'c', disabledReason: 'The folder may not contain ..', onDrop: () => undefined, onPick: () => undefined }));
	assert.match(html, /The folder may not contain \.\./);
	assert.equal((html.match(/<button[^>]*disabled=""/g) ?? []).length, 2);
	assert.match(html, /aria-disabled="true"/);
});

test('UploadList: each row shows its path and words; uploading rows have a progress bar; failures keep the engine text behind a disclosure', () => {
	const base: UploadRow = { id: 'u1', path: 'docs/a.md', name: 'a.md', objectId: 'o', size: 100, status: 'uploading', bytesSent: 40, fileSize: 100, chunks: null, existingChunks: null, message: null, detail: null };
	const html = render(
		h(UploadList, {
			rows: [base, { ...base, id: 'u2', path: 'b.pdf', status: 'failed', message: "Failed. The engine did not return the reason; the pipeline's run log may. The document was not added.", detail: 'Pipe closed with an error' }, { ...base, id: 'u3', path: 'c.md', status: 'done', chunks: 7 }],
			notes: ['Skipped 1 hidden or system file.'],
			onClearFinished: () => undefined,
		})
	);
	assert.match(html, /aria-label="Uploads"/);
	assert.match(html, /role="progressbar" aria-label="Uploading docs\/a.md" aria-valuemin="0" aria-valuemax="100" aria-valuenow="40"/);
	assert.match(html, /Uploading… 40%/);
	assert.match(html, /Failed\. The engine did not return the reason/);
	assert.match(html, /<details[^>]*><summary>What the engine said<\/summary>Pipe closed with an error<\/details>/);
	assert.match(html, /7 chunks added/);
	assert.match(html, /Skipped 1 hidden or system file\./);
	assert.match(html, />Clear finished</);
	assert.equal(render(h(UploadList, { rows: [], notes: [], onClearFinished: () => undefined })), '');
});

test('ReplaceConfirmDialog: the question, the list of paths and both buttons', () => {
	const one = render(h(ReplaceConfirmDialog, { question: replaceQuestion([{ rowId: 'r', path: 'report.pdf', state: 'exists', chunks: 19 }]), onReplace: () => undefined, onCancel: () => undefined }));
	assert.match(one, /Replace existing &#x27;report.pdf&#x27; \(19 chunks\)\? The old chunks are removed when the new file is stored\./);
	assert.match(one, />Cancel</);
	assert.match(one, />Replace document</);
	const many = render(
		h(ReplaceConfirmDialog, {
			question: replaceQuestion([
				{ rowId: 'a', path: 'a.md', state: 'exists', chunks: 2 },
				{ rowId: 'b', path: 'b.md', state: 'exists', chunks: 3 },
			]),
			onReplace: () => undefined,
			onCancel: () => undefined,
		})
	);
	assert.match(many, /<li[^>]*>a\.md \(2 chunks\)<\/li>/);
	assert.match(many, /Cancel sends none of these files/);
});

// ── Chat ────────────────────────────────────────────────────────────────────

test('ChatPanel: an answer with its sources, the stub mark, the threshold and "Why these?"', async () => {
	forgetChatAndIngest();
	const session = chatSessionFor('render-1', { ask: async () => chatAnswer, makeQuestion: (text) => ({ text }), now: () => 0, announce: () => undefined });
	await session.send('Where does Falcon Station get its drinking water?', null);
	const html = render(h(ChatPanel, { model: model(), channels, selection: createSelectionStore('render-1'), actions, scope: null, onClearScope: () => undefined }));
	assert.match(html, /Answers by Local stub LLM/);
	assert.match(html, /You:<\/span>Where does Falcon Station get its drinking water\?/);
	assert.match(html, /data-markdown="answer"/);
	assert.match(html, /\[STUB-LLM\] deterministic answer/);
	assert.match(html, />Stub LLM</);
	assert.match(html, /3 sources · 0\.58 top/);
	assert.match(html, /threshold 0\.30/);
	assert.match(html, /aria-expanded="false"[^>]*>Why these\?</);
	assert.match(html, /aria-label="Open C:\/demo\/handbooks\/falcon_handbook.md at chunk 0"/);
	assert.match(html, /aria-label="Show chunk 4 of C:\/demo\/handbooks\/falcon_handbook.md on the map"/);
	assert.match(html, /aria-label="Ask about these documents"/);
	assert.match(html, /maxLength="4000"/i);
	forgetChatAndIngest();
});

test('ChatPanel: no "Why these?" without the embedding node; the scope chip when asking about chosen documents', async () => {
	forgetChatAndIngest();
	const session = chatSessionFor('render-1', { ask: async () => chatAnswer, makeQuestion: (text) => ({ text }), now: () => 0, announce: () => undefined });
	await session.send('q', null);
	const html = render(h(ChatPanel, { model: model({ embed: { enabled: false, reason: 'Text queries need the embedding node reachable from the Tools source' } }), channels, selection: createSelectionStore('render-1'), actions, scope: ['o1', 'o2'], onClearScope: () => undefined }));
	assert.doesNotMatch(html, /Why these\?/);
	assert.match(html, /Asking about 2 documents only/);
	assert.match(html, />Ask about all documents</);
	forgetChatAndIngest();
});

test('ChatPanel: a Search toggle in the header; the SearchPanel is mounted in the same space, hidden until it is on', async () => {
	forgetChatAndIngest();
	const html = render(h(ChatPanel, { model: model(), channels, selection: createSelectionStore('render-1'), actions, scope: null, onClearScope: () => undefined }));
	assert.match(html, /<button[^>]*aria-pressed="false"[^>]*>Search<\/button>/);
	const at = html.search(/<[a-z]+[^>]*data-component="SearchPanel"/);
	assert.ok(at >= 0, 'the panel is mounted');
	assert.match(html.slice(0, at), /<div hidden=""[^>]*>$/, 'inside a hidden wrapper while Search is off');
	if (html.slice(at, html.indexOf('>', at)).includes('data-placeholder')) assert.match(html.slice(at, at + 600), /Not built yet/);
	assert.match(html, /aria-label="Ask about these documents"/, 'the chat stays the panel shown');
	forgetChatAndIngest();
});

test('ChatPanel: without a Chat source it says so and offers no composer', () => {
	forgetChatAndIngest();
	const html = render(h(ChatPanel, { model: model(), channels: { ...channels, chat: null }, selection: createSelectionStore('render-1'), actions, scope: null, onClearScope: () => undefined }));
	assert.match(html, /Chat is not available/);
	assert.ok(html.includes(NO_CHAT_SENTENCE));
	assert.doesNotMatch(html, /<textarea/);
	forgetChatAndIngest();
});

test('SourcesPanel: chunk text is text, not markup; scores carry their formula', () => {
	const sources: IChatSource[] = parseChatResult({ documents: [{ page_content: '<script>alert(1)</script> water', score: 0.5757, metadata: { objectId: 'o1', chunkId: 2, parent: 'a/b.md' } }] }).sources;
	const html = render(h(SourcesPanel, { sources, score: dialect.score, onOpen: () => undefined, onShowOnMap: () => undefined }));
	assert.doesNotMatch(html, /<script/);
	assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt; water/);
	assert.match(html, /title="Score 0\.5757 \(1 - cosine_distance\)"/);
	assert.match(html, />0\.58</);
	assert.match(html, /#2/);
	assert.match(render(h(SourcesPanel, { sources: [], score: null, onOpen: () => undefined, onShowOnMap: () => undefined })), /The answer cited no stored chunks\./);
});

test('RetrievalDebugger: starts by embedding; renders nothing without the embedding node', () => {
	const on = render(h(RetrievalDebugger, { model: model(), channels, question: 'q', topK: 3, onClose: () => undefined }));
	assert.match(on, /aria-label="Why these sources"/);
	assert.match(on, /Embedding…/);
	const off = render(h(RetrievalDebugger, { model: model({ embed: { enabled: false, reason: 'x' } }), channels, question: 'q', topK: 3, onClose: () => undefined }));
	assert.equal(off, '');
});

test('ScoreHistogram: bars for the non-empty bins, the threshold and floor lines, a text alternative', () => {
	const html = render(h(ScoreHistogram, { scores: [0.5433, 0.5247, 0.19, 0.09], range: [-1, 1], threshold: 0.3, floor: 0.2 }));
	assert.equal((html.match(/<rect /g) ?? []).length, 4);
	assert.match(html, /data-line="threshold"/);
	assert.match(html, /data-line="floor"/);
	assert.match(html, /role="img" aria-label="Scores of 4 results from -1\.00 to 1\.00; threshold 0\.30, floor 0\.20\."/);
});
