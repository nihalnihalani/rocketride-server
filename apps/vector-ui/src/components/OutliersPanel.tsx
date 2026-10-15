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
// VECTOR-UI — OutliersPanel (the sample's least-dense points)
// =============================================================================
//
// Points whose neighbourhood in the node's kNN graph is the sparsest (the node
// reports the lowest 1 % by density): OCR noise, a stray table, a document that
// is unlike everything else. Each row selects the point on the map.
// =============================================================================

import React from 'react';
import type { OutliersPanelProps as ContractOutliersPanelProps } from '../contract/types';
import { documentOf } from '../map/model';
import { MAP_STYLES } from '../map/styles';

/** Props (frozen). */
export type OutliersPanelProps = ContractOutliersPanelProps;

/**
 * The outliers panel.
 *
 * @param props - Sample and select handler.
 * @returns A list of outlier points.
 */
export function OutliersPanel(props: OutliersPanelProps): React.ReactElement {
	const result = props.sample.result;
	if (result.outliers.length === 0) return <p style={MAP_STYLES.note}>No outliers in this sample.</p>;
	return (
		<>
			<p style={MAP_STYLES.note}>The points with the sparsest neighbourhoods in this sample (lowest density first). They are ringed on the map.</p>
			<ul aria-label="Outliers" style={MAP_STYLES.list}>
				{result.outliers.map((i) => (
					<li key={i} style={MAP_STYLES.row}>
						<button type="button" style={MAP_STYLES.linkButton} onClick={() => props.onSelect(i)}>
							{documentOf(result, i)?.path ?? '?'} #{result.points.chunk[i]}
						</button>
						<div style={MAP_STYLES.small}>density {(result.density[i] ?? 0).toFixed(3)}</div>
					</li>
				))}
			</ul>
		</>
	);
}

export default OutliersPanel;
