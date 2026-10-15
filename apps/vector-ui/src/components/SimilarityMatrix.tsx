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
// nearest-neighbour chaining, a legend in words, Export CSV and Show pair.
// Calls `similarity_matrix` with the selection's keys (never sample indices,
// so a re-drawn sample cannot shift the matrix) through map/calls.ts; the
// answer carries scalars only. A newer selection replaces an older answer.
// =============================================================================

import React, { useEffect, useState } from 'react';
import type { IRoleChannel } from 'shared/explorer';
import type { IExportItem, IVectorLimits, MatrixSource, SimilarityMatrixProps, VectorKey, VectorMetric } from '../contract/types';
import { callSimilarityMatrix } from '../map/calls';
import { chainOrder, matrixInput, matrixRange, matrixRows, reorder, shadeOf } from '../map/matrixOrder';
import { MATRIX_BUSY, MATRIX_NO_CHANNEL, PICK_A_PAIR, matrixCaption, matrixFailure, matrixLegend, matrixNotFound, matrixSourceLine, selectedPairLine } from '../map/reviewWording';
import { MAP_STYLES } from '../map/styles';

export type { SimilarityMatrixProps };

/** Largest matrix whose values are printed in its cells. */
export const IN_CELL_MAX = 20;

/** What the panel shows. */
export type MatrixState = { kind: 'blocked'; message: string } | { kind: 'busy' } | { kind: 'error'; message: string } | { kind: 'ok'; keys: VectorKey[]; matrix: number[][]; metric: VectorMetric; source: MatrixSource; notFound: VectorKey[]; dp?: number };

/**
 * Compute a selection's matrix on the store node and order it.
 *
 * @param channel - The channel that reaches the store node.
 * @param storeNode - The store node id.
 * @param keys - The selection's keys.
 * @param limits - The dialect's limits.
 * @returns The ordered matrix, the reason none was asked for, or the failure.
 */
export async function loadMatrix(channel: Pick<IRoleChannel, 'invoke'>, storeNode: string, keys: readonly VectorKey[], limits: IVectorLimits): Promise<MatrixState> {
	const plan = matrixInput(keys, limits);
	if ('blocker' in plan) return { kind: 'blocked', message: plan.blocker };
	const answer = await callSimilarityMatrix(channel, plan.input, { nodeId: storeNode });
	if (!answer.ok) return { kind: 'error', message: matrixFailure(answer.code, answer.message, limits.matrix_keys_max) };
	const result = answer.value;
	const ordered = reorder({ keys: result.keys, matrix: result.matrix }, chainOrder(result.matrix));
	return { kind: 'ok', keys: ordered.keys, matrix: ordered.matrix, metric: result.metric, source: result.source, notFound: result.not_found, dp: result.dp };
}

/**
 * The export entry of a matrix (rows built when it is chosen).
 *
 * @param keys - The keys, in display order.
 * @param matrix - The matrix in that order.
 * @param labelOf - Words for a key.
 * @returns The item.
 */
export function matrixExportItem(keys: readonly VectorKey[], matrix: ReadonlyArray<ReadonlyArray<number>>, labelOf: (key: VectorKey) => string): IExportItem {
	return { id: 'map-matrix', label: `Similarity matrix (${keys.length} × ${keys.length})`, kind: 'matrix', disabled: null, rows: () => matrixRows(keys, matrix, labelOf) };
}

/** What the panel's body is drawn from. */
export interface MatrixBodyProps {
	state: MatrixState;
	labelOf(key: VectorKey): string;
	/** The picked pair (display indices), or null. */
	selected: readonly [number, number] | null;
	showTable: boolean;
	canShowPair: boolean;
	canExport: boolean;
	onSelectPair(i: number, j: number): void;
	onToggleTable(): void;
	onShowPair(): void;
	onExport(): void;
}

/**
 * The heatmap: one cell per pair, darker for more similar, the value on
 * hover and (small matrices) in the cell. Hidden from screen readers: the
 * table is their view.
 *
 * @param props - The body's props.
 * @param ok - The matrix.
 * @returns The grid.
 */
function heatmap(props: MatrixBodyProps, ok: Extract<MatrixState, { kind: 'ok' }>): React.ReactElement {
	const n = ok.keys.length;
	const dp = ok.dp ?? 2;
	const range = matrixRange(ok.matrix);
	const size = n <= IN_CELL_MAX ? 28 : Math.max(3, Math.floor(300 / n));
	const labels = ok.keys.map((key) => props.labelOf(key));
	const cells: React.ReactElement[] = [];
	for (let i = 0; i < n; i += 1) {
		const row = ok.matrix[i] as number[];
		for (let j = 0; j < n; j += 1) {
			const value = row[j] as number;
			const picked = props.selected !== null && ((props.selected[0] === i && props.selected[1] === j) || (props.selected[0] === j && props.selected[1] === i));
			cells.push(
				<div key={`${i}-${j}`} data-cell={`${i}-${j}`} title={`${labels[i]} ↔ ${labels[j]}: ${value.toFixed(dp)}`} onClick={() => props.onSelectPair(i, j)} style={{ position: 'relative', width: size, height: size, background: 'var(--rr-bg-default)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: picked ? 'inset 0 0 0 2px var(--rr-text-primary)' : undefined }}>
					<div style={{ position: 'absolute', inset: 0, background: 'var(--rr-chart-blue)', opacity: 0.06 + 0.84 * shadeOf(value, range) }} />
					{n <= IN_CELL_MAX ? <span style={{ position: 'relative', fontSize: 8.5, lineHeight: 1.2, color: 'var(--rr-text-primary)', background: 'var(--rr-bg-paper)', borderRadius: 2, padding: '0 1px' }}>{value.toFixed(dp)}</span> : null}
				</div>
			);
		}
	}
	return (
		<div style={{ overflow: 'auto', maxWidth: '100%', margin: '6px 0' }}>
			<div aria-hidden="true" data-matrix-size={n} style={{ display: 'grid', gridTemplateColumns: `repeat(${n}, ${size}px)`, gap: 1, width: 'max-content' }}>
				{cells}
			</div>
		</div>
	);
}

/**
 * The table alternative: a header per key, each value a button that picks its pair.
 *
 * @param props - The body's props.
 * @param ok - The matrix.
 * @returns The table.
 */
function table(props: MatrixBodyProps, ok: Extract<MatrixState, { kind: 'ok' }>): React.ReactElement {
	const dp = ok.dp ?? 2;
	const labels = ok.keys.map((key) => props.labelOf(key));
	return (
		<div style={{ overflow: 'auto', maxWidth: '100%', maxHeight: 320 }}>
			<table style={MAP_STYLES.table} aria-label="Similarity matrix as a table">
				<thead>
					<tr>
						<td style={MAP_STYLES.th} />
						{labels.map((label, j) => (
							<th key={j} scope="col" style={MAP_STYLES.th}>
								{label}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{ok.matrix.map((row, i) => (
						<tr key={i}>
							<th scope="row" style={{ ...MAP_STYLES.td, fontWeight: 700, textAlign: 'left' }}>
								{labels[i]}
							</th>
							{row.map((value, j) => {
								const picked = props.selected !== null && props.selected[0] === i && props.selected[1] === j;
								return (
									<td key={j} style={MAP_STYLES.td}>
										<button type="button" style={MAP_STYLES.linkButton} aria-pressed={picked} aria-label={`${labels[i]} ↔ ${labels[j]}: ${value.toFixed(dp)}`} onClick={() => props.onSelectPair(i, j)}>
											{value.toFixed(dp)}
										</button>
									</td>
								);
							})}
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

/**
 * The panel's body: a plain function of its state (no hooks), so the tests
 * can call it and press its buttons.
 *
 * @param props - The state, the picked pair and the handlers.
 * @returns The body.
 */
export function MatrixBody(props: MatrixBodyProps): React.ReactElement {
	const { state } = props;
	if (state.kind !== 'ok') {
		return (
			<section aria-label="Similarity matrix" data-component="SimilarityMatrix" data-state={state.kind}>
				{state.kind === 'busy' ? (
					<p style={MAP_STYLES.note} role="status">
						{MATRIX_BUSY}
					</p>
				) : (
					<p style={MAP_STYLES.note}>{state.message}</p>
				)}
			</section>
		);
	}
	const dp = state.dp ?? 2;
	const range = matrixRange(state.matrix);
	const missing = matrixNotFound(state.notFound.map((key) => props.labelOf(key)));
	const pair = props.selected;
	return (
		<section aria-label="Similarity matrix" data-component="SimilarityMatrix" data-state="ok" data-n={state.keys.length}>
			<h4 style={{ ...MAP_STYLES.heading, fontSize: 12, marginTop: 10 }}>Similarity matrix</h4>
			<p style={MAP_STYLES.note}>{matrixCaption(state.keys.length, state.metric)}</p>
			<p style={MAP_STYLES.note}>{matrixSourceLine(state.source)}</p>
			{missing ? <p style={MAP_STYLES.note}>{missing}</p> : null}
			{heatmap(props, state)}
			<p style={MAP_STYLES.note}>{matrixLegend(range.min, range.max, dp)}</p>
			<p style={MAP_STYLES.small} role="status">
				{pair ? selectedPairLine(props.labelOf(state.keys[pair[0]] as VectorKey), props.labelOf(state.keys[pair[1]] as VectorKey), ((state.matrix[pair[0]] as number[])[pair[1]] as number).toFixed(dp)) : PICK_A_PAIR}
			</p>
			<div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0' }}>
				{props.canShowPair ? (
					<button type="button" style={MAP_STYLES.button} disabled={pair === null} onClick={() => props.onShowPair()}>
						Show pair
					</button>
				) : null}
				{props.canExport ? (
					<button type="button" style={MAP_STYLES.button} onClick={() => props.onExport()}>
						Export CSV
					</button>
				) : null}
				<button type="button" style={MAP_STYLES.button} aria-expanded={props.showTable} onClick={() => props.onToggleTable()}>
					{props.showTable ? 'Hide the table' : 'Show as a table'}
				</button>
			</div>
			{props.showTable ? table(props, state) : null}
		</section>
	);
}

/**
 * The similarity matrix of the selection.
 *
 * @param props - The frozen props: the selection's keys, limits, the channel, the store node, words for a key, the pair and export handlers.
 * @returns The panel.
 */
export function SimilarityMatrix(props: SimilarityMatrixProps): React.ReactElement {
	const { keys, limits, channel, storeNode } = props;
	const plan = matrixInput(keys, limits);
	const signature = JSON.stringify('input' in plan ? plan.input.keys : plan.blocker);
	const [state, setState] = useState<MatrixState>({ kind: 'busy' });
	const [selected, setSelected] = useState<readonly [number, number] | null>(null);
	const [showTable, setShowTable] = useState(false);

	useEffect(() => {
		if (!('input' in plan) || channel === null) return;
		let live = true;
		setState({ kind: 'busy' });
		setSelected(null);
		void loadMatrix(channel, storeNode, keys, limits).then((next) => {
			if (live) setState(next);
		});
		return () => {
			live = false;
		};
		// The keys are compared by value (signature); a new array of the same keys asks nothing.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [signature, channel, storeNode, limits.matrix_keys_max]);

	const shown: MatrixState = 'blocker' in plan ? { kind: 'blocked', message: plan.blocker } : channel === null ? { kind: 'blocked', message: MATRIX_NO_CHANNEL } : state;
	return (
		<MatrixBody
			state={shown}
			labelOf={props.labelOf}
			selected={selected}
			showTable={showTable}
			canShowPair={props.onShowPair !== undefined}
			canExport={props.onExport !== undefined}
			onSelectPair={(i, j) => setSelected([i, j])}
			onToggleTable={() => setShowTable((v) => !v)}
			onShowPair={() => {
				if (shown.kind !== 'ok' || selected === null) return;
				props.onShowPair?.(shown.keys[selected[0]] as VectorKey, shown.keys[selected[1]] as VectorKey);
			}}
			onExport={() => {
				if (shown.kind !== 'ok') return;
				props.onExport?.(matrixExportItem(shown.keys, shown.matrix, props.labelOf));
			}}
		/>
	);
}

export default SimilarityMatrix;
