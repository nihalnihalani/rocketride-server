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
// VECTOR-UI — PointInspector (the selected chunk, its neighbours, and actions)
// =============================================================================
//
// What the selected point is (path, chunk of N, length, text), how similar it
// is to the active query (and the pipeline's own score when known), its 12
// nearest chunks in the whole collection, and the actions that land back in the
// console: Open document, Find similar, Remove document (gated; when it is not
// available the reason is shown as text). Under the snippet, the chunk's full
// text panel (with the query's terms marked) once it is built.
// =============================================================================

import React from 'react';
import type { PointInspectorProps as ContractPointInspectorProps, VectorKey } from '../contract/types';
import { documentOf, pointKey } from '../map/model';
import { MAP_STYLES } from '../map/styles';
import { num } from '../map/wording';
import { ChunkTextPanel } from './ChunkTextPanel';
import { NeighbourList } from './NeighbourList';

/** Props: the frozen ones plus what the map fetched. */
export interface PointInspectorProps extends ContractPointInspectorProps {
	/** Full chunk text (light mode fetches it through `chunks`), or null. */
	text?: string | null;
	/** The pipeline's own score of this chunk for the query, when known. */
	score?: number | null;
	/** A busy line while neighbours or text load. */
	busy?: string | null;
	/** Why the neighbours could not be loaded. */
	error?: string | null;
	/** A neighbour row was chosen (select it on the map); defaults to Find similar. */
	onSelectNeighbour?(key: VectorKey): void;
}

/**
 * The inspector.
 *
 * @param props - Sample, point, neighbours, query similarity, write availability, actions.
 * @returns The panel.
 */
export function PointInspector(props: PointInspectorProps): React.ReactElement {
	const { sample, index } = props;
	if (index === null || index < 0 || index >= sample.result.n) {
		return <p style={MAP_STYLES.note}>Click a point or use the arrow keys to inspect a chunk. Enter selects, Escape clears.</p>;
	}
	const result = sample.result;
	const doc = documentOf(result, index);
	const [objectId, chunkId] = pointKey(result, index);
	const snippet = props.text ?? result.points.snip?.[index] ?? null;
	const removed = sample.removed.includes(objectId);
	return (
		<section aria-label="Selected chunk">
			<h3 style={MAP_STYLES.heading}>{doc?.path ?? objectId}</h3>
			<p style={MAP_STYLES.small}>
				Chunk {num(chunkId)}
				{doc?.chunks !== null && doc?.chunks !== undefined ? ` of ${num(doc.chunks)}` : ''} · {num(result.points.len[index] ?? 0)} characters
				{result.points.pinned[index] ? <span style={MAP_STYLES.tag}>pinned</span> : null}
				{removed ? <span style={MAP_STYLES.tag}>removed</span> : null}
			</p>
			{props.querySim !== null ? (
				<p style={MAP_STYLES.small}>
					Similarity to the query {props.querySim.toFixed(3)}
					{props.score !== null && props.score !== undefined ? ` · pipeline score ${props.score.toFixed(3)}` : ''}
				</p>
			) : null}
			{snippet ? <p style={{ ...MAP_STYLES.text, whiteSpace: 'pre-wrap', margin: '6px 0' }}>{snippet}</p> : <p style={MAP_STYLES.note}>This sample carries no text for its points (light mode).</p>}
			<ChunkTextPanel chunkKey={[objectId, chunkId]} text={props.text ?? null} />
			<div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
				<button type="button" style={MAP_STYLES.button} onClick={() => props.onOpenDocument(objectId, chunkId)}>
					Open document
				</button>
				<button type="button" style={MAP_STYLES.button} onClick={() => props.onFindSimilar([objectId, chunkId])}>
					Find similar
				</button>
				<button type="button" style={MAP_STYLES.button} disabled={!props.writes.enabled || removed} onClick={() => props.onRemoveDocument(objectId)}>
					Remove document
				</button>
			</div>
			{!props.writes.enabled && props.writes.reason ? <p style={MAP_STYLES.note}>{props.writes.reason}</p> : null}
			{props.busy ? (
				<p style={MAP_STYLES.note} role="status">
					{props.busy}
				</p>
			) : null}
			{props.error ? <p style={MAP_STYLES.note}>{props.error}</p> : null}
			{props.neighbours ? (
				<>
					<h4 style={{ ...MAP_STYLES.heading, fontSize: 12 }}>{num(props.neighbours.items.length)} nearest in the collection</h4>
					<NeighbourList items={props.neighbours.items} onSelect={(key) => (props.onSelectNeighbour ?? props.onFindSimilar)(key)} />
				</>
			) : null}
		</section>
	);
}

export default PointInspector;
