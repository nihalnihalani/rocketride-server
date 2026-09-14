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
// CONNECT — SESSION (tool invocation bound to one endpoint)
// =============================================================================
//
// Attach-mechanics live here on purpose (see types.ts). Today a session
// resolves the owning task's token lazily and drives the node's shared SQL
// tools (execute / get_schema / refresh_schema / dialect) via client.tool.
// When the attach path changes, this file changes — the ISqlSession contract
// does not.
// =============================================================================

import type { RocketRideClient } from 'shell';
import type {
	ISqlEndpoint,
	ISqlExecuteResult,
	ISqlProbeResult,
	ISqlSchemaResponse,
	ISqlSession,
	SqlDialect,
} from './types';

// =============================================================================
// DIALECT MAPPING
// =============================================================================

/** Dialect strings this app recognises from the node's `dialect` tool. */
const KNOWN_DIALECTS: ReadonlySet<string> = new Set(['mysql', 'postgres', 'clickhouse', 'neo4j']);

/**
 * Map a node-reported dialect string onto the app's SqlDialect union.
 *
 * @param value - The raw dialect string from the node.
 * @returns The matching SqlDialect, or 'unknown'.
 */
function toDialect(value: unknown): SqlDialect {
	return typeof value === 'string' && KNOWN_DIALECTS.has(value) ? (value as SqlDialect) : 'unknown';
}

// =============================================================================
// TOOL-SUPPORT PROBING
// =============================================================================

/**
 * Error fragments that mean "this node does not have that tool". The engine
 * walks the tool chain and, when no node owns the name, fails the call — the
 * wording is produced by the compiled engine, so only the Python side is
 * readable here (rocketlib's `tool.invoke: <name> not owned` and
 * `Unknown dynamic tool: <name>`). Matching is therefore best-effort.
 */
const UNSUPPORTED_TOOL_MARKERS = ['not owned', 'unknown tool', 'unknown dynamic tool', 'no tool methods', 'no node handles'];

/**
 * Error fragments that mean the tool RAN and the database refused the work.
 * These are the failures a capability fallback must NOT swallow.
 */
const EXECUTED_MARKERS = ['sql execution failed', 'max_execute_rows', 'is disabled for this node', 'transaction session'];

/**
 * Decide whether a failed tool call means the node does not support the tool.
 *
 * The engine's exact wording for an unowned tool lives in the compiled
 * engine and cannot be verified from this repository, so the classifier is
 * deliberately asymmetric: it answers FALSE only for errors that clearly came
 * from a tool that ran, and TRUE for everything else. A caller therefore
 * falls back on transient failures too — which is harmless, because the
 * fallback path fails the same way and surfaces the same error.
 *
 * @param err - The error a tool invocation threw.
 * @returns True when the failure should be treated as "tool unsupported".
 */
export function isUnsupportedToolError(err: unknown): boolean {
	const message = (err instanceof Error ? err.message : String(err ?? '')).toLowerCase();
	if (EXECUTED_MARKERS.some((marker) => message.includes(marker))) return false;
	if (UNSUPPORTED_TOOL_MARKERS.some((marker) => message.includes(marker))) return true;
	// Unclassifiable: assume unsupported so a capability probe degrades
	// instead of turning a new UI affordance into a hard failure.
	return true;
}

// =============================================================================
// SESSION IMPLEMENTATION
// =============================================================================

/**
 * ISqlSession over the pipeline tool transport: resolves the task token on
 * first use, invokes the node's tools through client.tool, and re-resolves
 * the token once on failure (the task may have restarted since binding).
 */
class SqlToolSession implements ISqlSession {
	/** The endpoint this session is bound to. */
	readonly endpoint: ISqlEndpoint;

	/** The shell's RocketRide client (owned by the shell, never by this app). */
	private readonly client: RocketRideClient;

	/** Cached task token; null until first resolution or after invalidation. */
	private token: string | null = null;

	/**
	 * @param client - The shell's RocketRide client.
	 * @param endpoint - The endpoint to bind to.
	 */
	constructor(client: RocketRideClient, endpoint: ISqlEndpoint) {
		this.client = client;
		this.endpoint = endpoint;
	}

	/**
	 * Resolve (and cache) the token of the task owning this endpoint.
	 *
	 * @returns The task token.
	 * @throws When no task is currently running for the endpoint's pipeline.
	 */
	private async resolveToken(): Promise<string> {
		if (this.token) return this.token;
		const token = await this.client.getTaskToken({
			projectId: this.endpoint.projectId,
			source: this.endpoint.source,
		});
		if (!token) {
			throw new Error(`No running task for pipeline '${this.endpoint.pipelineName}' — start the pipeline and retry.`);
		}
		this.token = token;
		return token;
	}

	/**
	 * Invoke one of the node's tools, retrying exactly once with a fresh token
	 * when the first attempt fails (covers task restarts between calls).
	 *
	 * @param tool - Tool name (execute / get_schema / refresh_schema / dialect).
	 * @param input - Tool input arguments.
	 * @returns The tool's result value.
	 */
	private async invoke<T>(tool: string, input: Record<string, unknown>): Promise<T> {
		const token = await this.resolveToken();
		try {
			return await this.client.tool<T>({ token, tool, nodeId: this.endpoint.nodeId, input });
		} catch (err) {
			// One retry with a re-resolved token: the cached token goes stale
			// whenever the owning task restarts. Any second failure is real.
			this.token = null;
			const fresh = await this.resolveToken();
			if (fresh === token) throw err;
			return await this.client.tool<T>({ token: fresh, tool, nodeId: this.endpoint.nodeId, input });
		}
	}

	/** @inheritdoc */
	async execute(sql: string, opts?: { params?: unknown[] }): Promise<ISqlExecuteResult> {
		// Omit `params` entirely when there is nothing to bind: the node's
		// placeholder rewriting is skipped for an empty list, so an unbound
		// statement keeps travelling exactly as it did before.
		const params = opts?.params;
		const input = params && params.length > 0 ? { sql, params } : { sql };
		return this.invoke<ISqlExecuteResult>('execute', input);
	}

	/** @inheritdoc */
	async getSchema(table?: string): Promise<ISqlSchemaResponse> {
		return this.invoke<ISqlSchemaResponse>('get_schema', table ? { table } : {});
	}

	/** @inheritdoc */
	async refreshSchema(): Promise<ISqlSchemaResponse> {
		try {
			return await this.invoke<ISqlSchemaResponse>('refresh_schema', {});
		} catch (err) {
			if (!isUnsupportedToolError(err)) throw err;
			// Older nodes have no refresh tool: serve the task-start snapshot
			// and say so, rather than presenting it as freshly reflected.
			const schema = await this.getSchema();
			return { ...schema, stale: true };
		}
	}

	/** @inheritdoc */
	async dialect(): Promise<SqlDialect> {
		const result = await this.invoke<{ dialect?: string }>('dialect', {});
		return toDialect(result?.dialect);
	}
}

// =============================================================================
// FACTORY + PROBE
// =============================================================================

/**
 * Create a live session bound to one database endpoint.
 *
 * @param client - The shell's RocketRide client.
 * @param endpoint - The endpoint to bind to.
 * @returns The bound session.
 */
export function createSqlSession(client: RocketRideClient, endpoint: ISqlEndpoint): ISqlSession {
	return new SqlToolSession(client, endpoint);
}

/**
 * Probe an endpoint before binding to it: report dialect and a shallow
 * schema summary. Never throws — failures come back as `ok: false`.
 *
 * @param client - The shell's RocketRide client.
 * @param endpoint - The endpoint to probe.
 * @returns The probe result.
 */
export async function probeSqlEndpoint(client: RocketRideClient, endpoint: ISqlEndpoint): Promise<ISqlProbeResult> {
	const session = createSqlSession(client, endpoint);
	try {
		// Dialect first (cheapest), then a full reflection for the summary.
		const dialect = await session.dialect();
		const schema = await session.getSchema();
		if (schema.error) {
			return { ok: false, dialect, error: schema.error };
		}
		return {
			ok: true,
			dialect,
			database: schema.database,
			tableCount: schema.tables ? Object.keys(schema.tables).length : 0,
		};
	} catch (err) {
		return { ok: false, dialect: 'unknown', error: err instanceof Error ? err.message : String(err) };
	}
}
