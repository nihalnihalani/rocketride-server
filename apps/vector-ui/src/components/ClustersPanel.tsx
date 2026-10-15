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
// VECTOR-UI — ClustersPanel (the map's Clusters tab)
// =============================================================================
//
// One row per cluster of the sample's neighbour graph, largest first, with its
// colour, its label (the node's keywords), its size and documents, and Show,
// Ask about these and Export; a Noise row; a Minimum size select applied in the
// browser (no call). The clusters come with the sample from a node that
// computes them (contract section 4.4-C; capability `clusters`).
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { ClustersPanelProps } from '../contract/types';

export type { ClustersPanelProps };

/**
 * ClustersPanel: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function ClustersPanel(_props: ClustersPanelProps): React.ReactElement {
	return (
		<section aria-label="Clusters" data-component="ClustersPanel" data-placeholder="">
			<p role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 12, lineHeight: 1.45, margin: '4px 0', padding: '6px 8px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: clusters of this sample, with their labels.
			</p>
		</section>
	);
}

export default ClustersPanel;
