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
// VECTOR-UI — RecommendPanel (the map's Recommend tab)
// =============================================================================
//
// Chunks like the positive examples and unlike the negative ones, from the
// whole collection: the examples as removable chips, the strategy (Average
// vector; Best score where the store ranks natively), k, Run, and the results
// with map and Pin. The map runs the call (it holds the query vector).
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { RecommendPanelProps } from '../contract/types';

export type { RecommendPanelProps };

/**
 * RecommendPanel: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function RecommendPanel(_props: RecommendPanelProps): React.ReactElement {
	return (
		<section aria-label="Recommend" data-component="RecommendPanel" data-placeholder="">
			<p role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 12, lineHeight: 1.45, margin: '4px 0', padding: '6px 8px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: recommend from positive and negative examples.
			</p>
		</section>
	);
}

export default RecommendPanel;
