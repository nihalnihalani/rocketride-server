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
// VECTOR-UI — ChunkTextPanel (a chunk's full text, in the point inspector)
// =============================================================================
//
// The selected chunk's full text (fetched once per key) with the active
// query's terms marked, "Lexical matches only; retrieval is by meaning",
// and Previous / Next chunk. The marks are text segments, never HTML.
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { ChunkTextPanelProps } from '../contract/types';

export type { ChunkTextPanelProps };

/**
 * ChunkTextPanel: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function ChunkTextPanel(_props: ChunkTextPanelProps): React.ReactElement {
	return (
		<section aria-label="Chunk text" data-component="ChunkTextPanel" data-placeholder="">
			<p role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 12, lineHeight: 1.45, margin: '4px 0', padding: '6px 8px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: the chunk's full text with the query's terms marked.
			</p>
		</section>
	);
}

export default ChunkTextPanel;
