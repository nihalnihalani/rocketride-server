// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

// =============================================================================
// PIPELINE TEMPLATES: tools_1 plus one graph node, execute off, no secrets
// =============================================================================

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { GRAPH_PROVIDERS } from '../src/adapters/explorer';

interface IComponent {
	id: string;
	provider: string;
	name?: string;
	config: Record<string, unknown>;
	control?: Array<{ classType: string; from: string }>;
}

const DIR = path.resolve(__dirname, '..', 'templates');
const FILES = ['age', 'neo4j', 'falkordb'];
const PROVIDER_OF: Record<string, string> = { age: 'rocketride_graph', neo4j: 'graph_neo4j', falkordb: 'graph_falkordb' };

/** Read a template. */
function read(key: string): { components: IComponent[]; project_id: string } {
	return JSON.parse(fs.readFileSync(path.join(DIR, `${key}.pipe`), 'utf8'));
}

test('exactly the three templates exist, and each is valid JSON', () => {
	assert.deepEqual(fs.readdirSync(DIR).sort(), FILES.map((f) => `${f}.pipe`).sort());
	for (const key of FILES) assert.ok(read(key).components.length > 0, key);
});

test('each template is a tools source plus one graph node of the right provider, wired as a tool', () => {
	for (const key of FILES) {
		const { components } = read(key);
		const tools = components.find((c) => c.id === 'tools_1');
		assert.equal(tools?.provider, 'tools');
		assert.equal(tools?.config.mode, 'Source');
		assert.equal(tools?.config.type, 'tools');
		const graphs = components.filter((c) => GRAPH_PROVIDERS.has(c.provider));
		assert.equal(graphs.length, 1, `${key}: exactly one graph node`);
		assert.equal(graphs[0].provider, PROVIDER_OF[key]);
		assert.deepEqual(graphs[0].control, [{ classType: 'tool', from: 'tools_1' }]);
		const others = components.filter((c) => c !== tools && c !== graphs[0]).map((c) => c.provider);
		assert.deepEqual(others, ['annotation'], `${key}: only a note beside the two nodes`);
	}
});

test('writes are off in every template: allow_execute false, and FalkorDB allow_writes false', () => {
	for (const key of FILES) {
		const graph = read(key).components.find((c) => GRAPH_PROVIDERS.has(c.provider))!;
		const settings = graph.config.default as Record<string, unknown>;
		assert.equal(settings.allow_execute, false, key);
		if (key === 'falkordb') assert.equal(settings.allow_writes, false);
	}
});

test('no template holds a password, token, key or a URL with credentials in it', () => {
	for (const key of FILES) {
		const raw = fs.readFileSync(path.join(DIR, `${key}.pipe`), 'utf8');
		const graph = read(key).components.find((c) => GRAPH_PROVIDERS.has(c.provider))!;
		const settings = graph.config.default as Record<string, unknown>;
		for (const name of ['password', 'token', 'url', 'api_key', 'apikey', 'secret']) assert.ok(!(name in settings), `${key} sets ${name}`);
		assert.doesNotMatch(raw, /:\/\/[^\s"/]*:[^\s"/]*@/, `${key} has a URL with credentials`);
		assert.doesNotMatch(raw, /"(password|token|secret|api_?key)"\s*:\s*"[^"]/i, `${key} has a secret value`);
	}
});

test('project ids are distinct UUIDs, so two templates never share an endpoint identity', () => {
	const ids = FILES.map((key) => read(key).project_id);
	assert.equal(new Set(ids).size, FILES.length);
	for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test('the Neo4j note recommends a read-only database role and says reads are a routing hint, not access control', () => {
	const note = read('neo4j').components.find((c) => c.provider === 'annotation')!;
	const text = String(note.config.content);
	assert.match(text, /read-only database role/i);
	assert.match(text, /routing hint/i);
	assert.match(text, /not access control/i);
});

test('every note says the template cannot write, and how to get Ask', () => {
	for (const key of FILES) {
		const text = String(read(key).components.find((c) => c.provider === 'annotation')!.config.content);
		assert.match(text, /Nothing here can write/, key);
		assert.match(text, /add an LLM node/i, key);
	}
});
