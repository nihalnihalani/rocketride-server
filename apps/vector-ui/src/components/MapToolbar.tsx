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
// VECTOR-UI — MapToolbar (sample, layout, colour, query, lasso, fit, table)
// =============================================================================
//
// Sample: how many points and which mode (Detailed up to the node's sample_max,
// Light up to sample_max_light), and "New sample" draws another with the next
// seed. Layout: PCA (the node's own), Neighbour graph (seeded force layout over
// the kNN graph), t-SNE (at most 1,000 points; disabled with its reason above
// that). A running layout shows "Laying out…" and Cancel. Colour by, the text
// query (disabled with its reason when the embedding node is unreachable), and
// the Lasso, Fit and Table toggles. Native controls with labels; no key
// listeners of its own.
// =============================================================================

import React, { useState } from 'react';
import type { ColourBy, MapLayout, MapToolbarProps as ContractMapToolbarProps, SampleMode } from '../contract/types';
import { MAP_STYLES } from '../map/styles';
import { num } from '../map/wording';

/** Props: the frozen ones plus map extras. */
export interface MapToolbarProps extends ContractMapToolbarProps {
	/** Why t-SNE is unavailable for this sample, or null. */
	tsneReason?: string | null;
	/** Show Cancel (a layout is running). */
	canCancel?: boolean;
	/** The 3D toggle (PCA only), when offered. */
	threeD?: boolean;
	onToggle3D?(): void;
}

/** Detailed and light sizes offered (capped by the node's limits). */
const DETAILED_SIZES = [250, 500, 1000, 2000];
const LIGHT_SIZES = [3000, 5000];

const LAYOUTS: Array<{ id: MapLayout; label: string }> = [
	{ id: 'pca', label: 'PCA' },
	{ id: 'neighbour-graph', label: 'Neighbour graph' },
	{ id: 'tsne', label: 't-SNE (≤1,000)' },
];

const COLOURS: Array<{ id: ColourBy; label: string }> = [
	{ id: 'document', label: 'Document' },
	{ id: 'folder', label: 'Folder' },
	{ id: 'type', label: 'File type' },
	{ id: 'chunk-position', label: 'Chunk position' },
	{ id: 'query-similarity', label: 'Query similarity' },
	{ id: 'density', label: 'Density' },
];

/**
 * The map toolbar.
 *
 * @param props - Limits, sample, state and handlers.
 * @returns The toolbar.
 */
export function MapToolbar(props: MapToolbarProps): React.ReactElement {
	const [text, setText] = useState('');
	const sample = props.sample;
	const mode: SampleMode = sample?.mode ?? 'detailed';
	const n = sample?.result.n_requested ?? Math.min(props.limits.sample_default, props.limits.sample_max);
	const seed = sample?.seed ?? 7;
	const sizes = [...DETAILED_SIZES.filter((s) => s <= props.limits.sample_max).map((s) => ({ mode: 'detailed' as const, n: s })), ...LIGHT_SIZES.filter((s) => s <= props.limits.sample_max_light && s > props.limits.sample_max).map((s) => ({ mode: 'light' as const, n: s }))];
	const current = `${mode}:${n}`;
	if (!sizes.some((s) => `${s.mode}:${s.n}` === current)) sizes.push({ mode, n });
	const busy = props.busy !== null;
	const toggle = (pressed: boolean): React.CSSProperties => ({ ...MAP_STYLES.button, ...(pressed ? MAP_STYLES.buttonPressed : {}) });
	return (
		<div role="toolbar" aria-label="Map controls" style={MAP_STYLES.toolbar}>
			<label style={MAP_STYLES.group}>
				<span style={MAP_STYLES.label}>Points</span>
				<select
					aria-label="Points"
					style={MAP_STYLES.select}
					value={current}
					disabled={busy}
					onChange={(event) => {
						const [m, size] = event.target.value.split(':');
						props.onSample({ n: Number(size), mode: m === 'light' ? 'light' : 'detailed', seed });
					}}
				>
					{sizes.map((s) => (
						<option key={`${s.mode}:${s.n}`} value={`${s.mode}:${s.n}`}>
							{num(s.n)} {s.mode === 'light' ? '(light: no text)' : '(detailed)'}
						</option>
					))}
				</select>
			</label>
			{sample ? (
				<span style={MAP_STYLES.small}>
					of {sample.result.of.chunks === null ? '—' : num(sample.result.of.chunks)} chunks · {sample.result.of.documents === null ? '—' : num(sample.result.of.documents)} docs · seed {seed}
				</span>
			) : null}
			<button type="button" style={MAP_STYLES.button} disabled={busy} onClick={() => props.onSample({ n, mode, seed: seed + 1 })}>
				New sample
			</button>
			<label style={MAP_STYLES.group}>
				<span style={MAP_STYLES.label}>Layout</span>
				<select aria-label="Layout" style={MAP_STYLES.select} value={props.layout} disabled={busy || !sample} onChange={(event) => props.onLayout(event.target.value as MapLayout)}>
					{LAYOUTS.map((l) => (
						<option key={l.id} value={l.id} disabled={l.id === 'tsne' && !!props.tsneReason} title={l.id === 'tsne' ? (props.tsneReason ?? undefined) : undefined}>
							{l.label}
						</option>
					))}
				</select>
			</label>
			{props.canCancel ? (
				<button type="button" style={MAP_STYLES.button} onClick={props.onCancel}>
					Cancel
				</button>
			) : null}
			<label style={MAP_STYLES.group}>
				<span style={MAP_STYLES.label}>Colour by</span>
				<select aria-label="Colour by" style={MAP_STYLES.select} value={props.colourBy} onChange={(event) => props.onColourBy(event.target.value as ColourBy)}>
					{COLOURS.map((c) => (
						<option key={c.id} value={c.id}>
							{c.label}
						</option>
					))}
				</select>
			</label>
			<form
				style={MAP_STYLES.group}
				onSubmit={(event) => {
					event.preventDefault();
					if (props.query.enabled && text.trim() !== '' && !busy) props.onQuery(text.trim());
				}}
			>
				<label style={MAP_STYLES.group}>
					<span style={MAP_STYLES.label}>Query</span>
					<input aria-label="Query" style={MAP_STYLES.input} type="search" value={text} maxLength={8000} placeholder="Place a question on the map" disabled={!props.query.enabled} onChange={(event) => setText(event.target.value)} />
				</label>
				<button type="submit" style={MAP_STYLES.button} disabled={!props.query.enabled || busy || text.trim() === ''}>Run</button>
			</form>
			<button type="button" style={toggle(props.lasso)} aria-pressed={props.lasso} onClick={props.onToggleLasso} disabled={!sample}>Lasso</button>
			<button type="button" style={MAP_STYLES.button} onClick={props.onFit} disabled={!sample}>
				Fit
			</button>
			<button type="button" style={toggle(props.table)} aria-pressed={props.table} onClick={props.onToggleTable} disabled={!sample}>Table</button>
			{props.onToggle3D ? (
				<button type="button" style={toggle(!!props.threeD)} aria-pressed={!!props.threeD} onClick={props.onToggle3D} disabled={!sample || props.layout !== 'pca'}>3D</button>
			) : null}
			{props.busy ? (
				<span role="status" style={MAP_STYLES.small}>
					{props.busy}
				</span>
			) : null}
			{!props.query.enabled && props.query.reason ? <span style={MAP_STYLES.small}>{props.query.reason}</span> : null}
			{props.tsneReason ? <span style={MAP_STYLES.small}>{props.tsneReason}</span> : null}
		</div>
	);
}

export default MapToolbar;
