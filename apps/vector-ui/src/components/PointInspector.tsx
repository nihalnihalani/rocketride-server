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
// VECTOR-UI — PointInspector (placeholder)
// =============================================================================
//
// Placeholder until the real component lands: it exports the frozen props
// (src/contract/types.ts) and renders a framed "Not built yet" notice, so the
// files that render it compile and run today. Keep the export names and the
// props type when replacing it.
// =============================================================================

import React from 'react';
import { EmptyState } from 'shell';
import type { PointInspectorProps } from '../contract/types';

export type { PointInspectorProps };

/** Dashed frame that marks the placeholder on screen. */
const FRAME: React.CSSProperties = {
	border: '1px dashed var(--rr-border-input)',
	borderRadius: 6,
	padding: 12,
};

/**
 * Placeholder for the inspector of the selected map point.
 *
 * @param _props - The frozen props (unused until the component is built).
 * @returns A framed "Not built yet" notice.
 */
export function PointInspector(_props: PointInspectorProps): React.ReactElement {
	return (
		<div style={FRAME} data-placeholder="PointInspector">
			<EmptyState title="Not built yet" description="Details of the selected point will appear here." />
		</div>
	);
}

export default PointInspector;
