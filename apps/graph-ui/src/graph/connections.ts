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
// GRAPH - CONNECTIONS: card and drawer content, and what an empty list may claim
// =============================================================================
//
// Pure functions from an endpoint (token-free) and its probe to the text the
// connections page shows. Nothing here reads or prints a credential: the only
// identity shown is what the node's `dialect` answer publishes (engine, version,
// database or graph, whether `execute` is allowed) plus the endpoint's own
// pipeline, run kind and owner.
//
// WHAT AN EMPTY LIST CAN SAY
// A graph node that fails to START never appears in the task list at all, so an
// empty list is NOT evidence that a graph was never provisioned, and this app
// has no authorised status API that could prove it. The three states are kept
// apart on purpose:
//
//   none-running   no running supported graph node was found. Cause unknown:
//                  nothing started, still starting, or a node that failed to
//                  start. The text gives troubleshooting steps and says what
//                  is unknown.
//   unreachable    nodes were found but none could be reached or used (stopped,
//                  unreachable, or no permission). They exist; the card says why.
//   unprovisioned  claimed ONLY when a probe returned text that positively says
//                  the graph does not exist. Nothing in an empty list produces it.
// =============================================================================

import type { IExplorerEndpoint, IProbeResult } from 'shared/explorer';
import { CAPABILITY_POLICY, canWrite, engineText, parseDialect, readBoundaryText, supportsReadQuery, targetText } from './dialect';
import type { ICapabilityPolicy } from './dialect';

// =============================================================================
// TYPES
// =============================================================================

/** A badge: a variant for colour and a label that carries the whole message. */
export interface IBadge {
	variant: 'success' | 'muted' | 'error' | 'warning';
	label: string;
}

/** One line of detail. */
export interface IDetailRow {
	label: string;
	value: string;
}

/** What a card and its drawer show for one endpoint. */
export interface IConnectionView {
	title: string;
	/** The card's second line. */
	address: string;
	badge: IBadge;
	/** Lines for the drawer's identity section. */
	details: IDetailRow[];
	/** Sentences that qualify what the app will do (upgrade needed, read boundary, writes). */
	notes: string[];
	/** True when the connection can be opened for browsing. */
	openable: boolean;
	/** Why it cannot be opened, when it cannot. */
	blocked: string | null;
}

/** The empty states of the connections page. */
export type EmptyKind = 'loading' | 'none-running' | 'unreachable' | 'unprovisioned' | 'error';

/** The text for an empty state. */
export interface IEmptyState {
	kind: EmptyKind;
	title: string;
	description: string;
	/** What this app cannot tell, stated outright. */
	unknown: string | null;
}

// =============================================================================
// CARDS
// =============================================================================

/** The badge each endpoint state wears (the label carries the message; colour never does alone). */
export const STATE_BADGE: Record<IExplorerEndpoint['state'], IBadge> = {
	probing: { variant: 'muted', label: 'Checking' },
	ready: { variant: 'success', label: 'Running' },
	stopped: { variant: 'muted', label: 'Stopped' },
	unreachable: { variant: 'error', label: 'Unreachable' },
	inaccessible: { variant: 'error', label: 'No access' },
};

/**
 * The owner line: whose run this is. A deployment is named as one (a developer's
 * run and a deployment of the same pipeline are different connections), and the
 * team shown is the TASK's owning team, never the currently selected one.
 *
 * @param endpoint - The endpoint.
 * @returns e.g. `your development run` or `team deployment (team 4f2a)`.
 */
export function ownerText(endpoint: IExplorerEndpoint): string {
	const who = endpoint.ownerKind === 'team' ? `team ${endpoint.ownerId}` : endpoint.teamId ? `user ${endpoint.ownerId} (team ${endpoint.teamId})` : `user ${endpoint.ownerId}`;
	return endpoint.runKind === 'deploy' ? `deployment, ${who}` : `development run, ${who}`;
}

/**
 * Everything a card and drawer show for one endpoint.
 *
 * @param endpoint - The endpoint (token-free).
 * @param probe - Its probe result, when one exists.
 * @param policy - Whether nodes publish capabilities (default: the app's policy).
 * @returns The view.
 */
export function connectionView(endpoint: IExplorerEndpoint, probe: IProbeResult | undefined, policy: ICapabilityPolicy = CAPABILITY_POLICY): IConnectionView {
	const dialect = probe?.ok ? parseDialect(probe.info) : null;
	const details: IDetailRow[] = [
		{ label: 'Pipeline', value: endpoint.pipelineName || '(unnamed)' },
		{ label: 'Node', value: `${endpoint.nodeName || endpoint.nodeId} (${endpoint.provider})` },
		{ label: 'Run', value: ownerText(endpoint) },
	];
	const notes: string[] = [];
	let blocked: string | null = null;

	if (endpoint.state === 'stopped') blocked = 'The pipeline is stopped. Start it to browse this graph.';
	else if (endpoint.state === 'inaccessible') blocked = endpoint.stateDetail ?? 'You can see this task but you are not allowed to call its tools.';
	else if (endpoint.state === 'unreachable') blocked = endpoint.stateDetail ?? 'The node did not answer. It may still be starting or may have failed.';

	if (dialect) {
		details.push({ label: 'Engine', value: engineText(dialect) });
		const target = targetText(dialect);
		if (target) details.push({ label: 'Target', value: target });
		details.push({ label: 'Writes', value: canWrite(dialect, policy) ? 'Allowed (execute is on for this node)' : 'Off (browsing only)' });
		notes.push(readBoundaryText(dialect));
		if (!supportsReadQuery(dialect, policy)) {
			notes.push('This node does not support read_query yet. Upgrade the node to browse it with Graph Explorer.');
			blocked = blocked ?? 'This node needs an upgrade before it can be browsed.';
		}
	} else if (probe && !probe.ok && endpoint.state === 'ready') {
		blocked = blocked ?? probe.error?.message.split('\n')[0] ?? 'The node did not answer its identity probe.';
	}

	const badge = endpoint.state === 'ready' && dialect && !supportsReadQuery(dialect, policy) ? { variant: 'warning' as const, label: 'Needs upgrade' } : STATE_BADGE[endpoint.state];
	return {
		title: endpoint.nodeName || endpoint.nodeId,
		address: `${endpoint.provider} · ${endpoint.pipelineName}${endpoint.runKind === 'deploy' ? ' (deployment)' : ''}`,
		badge,
		details,
		notes,
		openable: blocked === null && endpoint.state === 'ready',
		blocked,
	};
}

// =============================================================================
// EMPTY STATES
// =============================================================================

/** Text in a probe error that positively says the graph does not exist. */
const UNPROVISIONED_EVIDENCE = /\bgraph\b[^\n]{0,80}\b(does not exist|not found|is missing|has not been created)\b/i;

/**
 * Which empty state applies, and what it may claim.
 *
 * @param status - The discovery lifecycle.
 * @param endpoints - The discovered endpoints.
 * @param probes - Probe results by endpoint key.
 * @param error - The discovery failure text, when it failed.
 * @returns The empty state, or null when there is something to show.
 */
export function emptyState(status: 'idle' | 'loading' | 'ready' | 'error', endpoints: readonly IExplorerEndpoint[], probes: Readonly<Record<string, IProbeResult>>, error: string | null): IEmptyState | null {
	if (status === 'idle' || (status === 'loading' && endpoints.length === 0)) {
		return { kind: 'loading', title: 'Discovering graph nodes', description: 'Scanning your running pipelines for Apache AGE, Neo4j and FalkorDB graph nodes...', unknown: null };
	}
	if (status === 'error' && endpoints.length === 0) {
		return { kind: 'error', title: 'Discovery failed', description: error ?? 'The list of running pipelines could not be read.', unknown: 'Nothing is known about which graph nodes are running.' };
	}
	if (endpoints.length === 0) {
		return {
			kind: 'none-running',
			title: 'No running graph node found',
			description: 'Start a pipeline that has a tools source wired to a graph node (rocketride_graph, graph_neo4j or graph_falkordb), then refresh. A pipeline that is still starting does not appear yet.',
			unknown: 'A graph node that fails to start does not appear in this list at all, so an empty list does not tell whether a graph exists for your organization or why a node is missing. Check the pipeline’s log for a start-up error.',
		};
	}
	const positive = endpoints.find((e) => {
		const message = probes[e.key]?.error?.message ?? '';
		return probes[e.key]?.ok === false && UNPROVISIONED_EVIDENCE.test(message);
	});
	if (positive && endpoints.every((e) => probes[e.key]?.ok === false)) {
		return { kind: 'unprovisioned', title: 'The graph does not exist yet', description: `The node answered that its graph is missing: ${(probes[positive.key]?.error?.message ?? '').split('\n')[0]}`, unknown: null };
	}
	if (endpoints.every((e) => e.state !== 'ready')) {
		return { kind: 'unreachable', title: 'Graph nodes found, but none can be used', description: 'Each card says why: the pipeline is stopped, the node did not answer, or you may not call its tools.', unknown: null };
	}
	return null;
}
