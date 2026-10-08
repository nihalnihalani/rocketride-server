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
// VECTOR-UI — DuplicatesPanel (near-duplicate pairs the node found in the sample)
// =============================================================================
//
// Pairs of sample points whose similarity is at or above the sample's
// duplicate threshold (0.97 by default), as the node computed them. "Show"
// highlights the pair on the map; "Remove" asks the console to remove one
// document (the console confirms; the control is gated like every write).
// =============================================================================

import React from 'react';
import type { DuplicatesPanelProps as ContractDuplicatesPanelProps } from '../contract/types';
import { documentOf, pointKey } from '../map/model';
import { MAP_STYLES } from '../map/styles';

/** Props (frozen). */
export type DuplicatesPanelProps = ContractDuplicatesPanelProps;

/** The last path segment. */
function base(path: string): string {
	const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
	return cut >= 0 ? path.slice(cut + 1) : path;
}

/**
 * The duplicates panel.
 *
 * @param props - Sample, write availability, handlers.
 * @returns A list of pairs.
 */
export function DuplicatesPanel(props: DuplicatesPanelProps): React.ReactElement {
	const result = props.sample.result;
	const removed = new Set(props.sample.removed);
	if (result.duplicates.length === 0) return <p style={MAP_STYLES.note}>No near-duplicate pairs at similarity 0.97 or above in this sample.</p>;
	return (
		<>
			<p style={MAP_STYLES.note}>Pairs of chunks that are nearly the same text, by the store&apos;s own similarity. The same file stored under two paths shows up here.</p>
			<ul aria-label="Near-duplicate pairs" style={MAP_STYLES.list}>
				{result.duplicates.map((pair) => {
					const a = documentOf(result, pair.a);
					const b = documentOf(result, pair.b);
					const [objectB] = pointKey(result, pair.b);
					const pathB = b?.path ?? objectB;
					return (
						<li key={`${pair.a}-${pair.b}`} style={MAP_STYLES.row}>
							<div style={MAP_STYLES.small}>
								{a?.path ?? '?'} #{result.points.chunk[pair.a]} ↔ {pathB} #{result.points.chunk[pair.b]} · similarity {pair.sim.toFixed(4)}
							</div>
							<div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
								<button type="button" style={MAP_STYLES.button} onClick={() => props.onSelect([pair.a, pair.b])}>
									Show
								</button>
								<button type="button" style={MAP_STYLES.button} disabled={!props.writes.enabled || removed.has(objectB)} title={props.writes.enabled ? undefined : (props.writes.reason ?? undefined)} onClick={() => props.onRemoveDocument(objectB)}>
									Remove {base(pathB)}
								</button>
							</div>
						</li>
					);
				})}
			</ul>
			{!props.writes.enabled && props.writes.reason ? <p style={MAP_STYLES.note}>{props.writes.reason}</p> : null}
		</>
	);
}

export default DuplicatesPanel;
