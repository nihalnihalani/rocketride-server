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
// CANVAS - EDGE (boundary-to-boundary line, parallel curve, self loop, arrow)
// =============================================================================
//
// All geometry comes from graph/geometry.ts. The component reads only the two
// end nodes' positions (`useInternalNode` re-renders an edge only when one of its
// own ends moves, never on pan or zoom or an unrelated node's drag) and draws
// what the pure functions return.
//
// Edges are not focusable and are hidden from the accessibility tree except for
// their `ariaLabel`: the keyboard and screen-reader path through the graph is
// the node-to-neighbour roving focus, and the Table view lists every
// relationship.
// =============================================================================

import React, { memo } from 'react';
import { useInternalNode } from '@xyflow/react';
import type { Edge, EdgeProps, InternalNode } from '@xyflow/react';
import { edgeShape } from '../graph/geometry';
import type { IEdgeSlot, Point } from '../graph/geometry';
import { NODE_DIAMETER } from './GraphNodeView';

/** What an edge renders. */
export interface IGraphEdgeData extends Record<string, unknown> {
	slot: IEdgeSlot;
	type: string;
	/** Draw in the brand colour (an endpoint is selected). */
	highlighted: boolean;
}

/** The React Flow edge type of a graph relationship. */
export type GraphFlowEdge = Edge<IGraphEdgeData, 'graphEdge'>;

/**
 * The centre of a node's circle in canvas units.
 *
 * @param node - A React Flow internal node.
 * @returns Its centre.
 */
function centerOf(node: InternalNode): Point {
	const width = node.measured?.width ?? NODE_DIAMETER;
	const height = node.measured?.height ?? NODE_DIAMETER;
	return { x: node.internals.positionAbsolute.x + width / 2, y: node.internals.positionAbsolute.y + height / 2 };
}

/**
 * One relationship of the graph canvas.
 *
 * @param props - React Flow edge props carrying {@link IGraphEdgeData}.
 * @returns The edge, or nothing while an end node has not been measured.
 */
function GraphEdgeViewImpl({ source, target, data }: EdgeProps<GraphFlowEdge>): React.ReactElement | null {
	const from = useInternalNode(source);
	const to = useInternalNode(target);
	if (!from || !to || !data) return null;
	const shape = edgeShape(centerOf(from), centerOf(to), data.slot, NODE_DIAMETER / 2, NODE_DIAMETER / 2);
	const stroke = data.highlighted ? 'var(--rr-brand)' : 'var(--rr-text-secondary)';
	return (
		<g className="graph-ui-edge">
			<path d={shape.path} fill="none" stroke={stroke} strokeWidth={data.highlighted ? 2 : 1.4} />
			<polygon points={shape.arrow} fill={stroke} />
			<text className="graph-ui-edge-label" x={shape.label.x} y={shape.label.y} transform={`rotate(${shape.labelAngle} ${shape.label.x} ${shape.label.y})`} textAnchor="middle" dominantBaseline="central">
				{data.type}
			</text>
		</g>
	);
}

/** The memoised edge component handed to React Flow's `edgeTypes`. */
export const GraphEdgeView = memo(GraphEdgeViewImpl);
