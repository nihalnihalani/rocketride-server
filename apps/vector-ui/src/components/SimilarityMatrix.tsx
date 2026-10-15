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
// VECTOR-UI — SimilarityMatrix (the map's Selection tab)
// =============================================================================
//
// The pairwise similarities of 2 to `limits.matrix_keys_max` selected chunks
// as a heatmap with a table alternative, rows and columns ordered by
// nearest-neighbour chaining, Export CSV and Show pair. Calls
// `similarity_matrix` with the selection's keys (never sample indices) through
// map/calls.ts; the answer carries scalars only.
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { SimilarityMatrixProps } from '../contract/types';

export type { SimilarityMatrixProps };

/**
 * SimilarityMatrix: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function SimilarityMatrix(_props: SimilarityMatrixProps): React.ReactElement {
	return (
		<section aria-label="Similarity matrix" data-component="SimilarityMatrix" data-placeholder="">
			<p role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 12, lineHeight: 1.45, margin: '4px 0', padding: '6px 8px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: the similarity matrix of the selection.
			</p>
		</section>
	);
}

export default SimilarityMatrix;
