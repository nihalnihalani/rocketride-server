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
// VECTOR-UI — STATS STRIP (R2: how many documents, chunks and more, at the top of the console)
// =============================================================================
//
// Renders vector/stats.ts: six figures ("—" with a reason for what the store
// did not count), the chips (each label carries its whole message), and
// "counts as of N s ago" after a quick refresh. While the first answer is
// pending it shows a skeleton; after a failure it keeps the last figures,
// marked "last known", under the shell's error banner. The Charts disclosure
// at the end, collapsed by default, holds the collection's charts.
// =============================================================================

import React, { useEffect, useState } from 'react';
import { Banner } from 'shell';
import type { IDialectResult, IDocumentItem } from '../contract/types';
import type { IStatsSlot } from '../vector/consoleStore';
import { TONE_EDGE } from '../vector/colors';
import { countsAsOfText, statsChips, statsFigures } from '../vector/stats';
import { styles } from '../styles';
import StatsCharts from './StatsCharts';

/** Props for the {@link StatsStrip} component. */
export interface IStatsStripProps {
	stats: IStatsSlot;
	dialect: IDialectResult | null;
	readOnly: boolean;
	/** The directory rows loaded so far (the charts read them). */
	documents?: readonly IDocumentItem[];
}

/** Re-render once a second so "counts as of N s ago" stays true. */
function useNow(): number {
	const [now, setNow] = useState(() => Date.now());
	useEffect(() => {
		const id = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(id);
	}, []);
	return now;
}

/**
 * The strip.
 *
 * @param props - {@link IStatsStripProps}.
 * @returns The strip element.
 */
export function StatsStrip({ stats, dialect, readOnly, documents = [] }: IStatsStripProps): React.ReactElement {
	const now = useNow();
	const figures = statsFigures(stats.view, dialect);
	const chips = statsChips({ dialect, stats: stats.view, readOnly });
	const asOf = countsAsOfText(stats.view, now);
	const pending = stats.view === null && stats.status !== 'error';
	const stale = stats.status === 'error' && stats.view !== null;
	return (
		<section aria-label="Database summary" style={{ padding: '10px 24px', borderBottom: '1px solid var(--rr-border)' }}>
			{stats.status === 'error' && stats.error && (
				<div style={{ marginBottom: 8 }}>
					<Banner variant="error">
						{stats.error.headline}
						{stats.error.detail ? ` ${stats.error.detail}` : ''}
					</Banner>
				</div>
			)}
			<dl style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 22px', margin: 0 }} aria-busy={pending}>
				{figures.map((f) => (
					<div key={f.key} style={{ display: 'flex', flexDirection: 'column', minWidth: 72 }} title={f.tooltip ?? undefined}>
						<dt style={{ ...styles.small, fontWeight: 600 }}>{f.label}</dt>
						<dd style={{ margin: 0, fontSize: f.key === 'model' || f.key === 'metric' ? 13 : 18, fontWeight: 600, fontStyle: stale ? 'italic' : 'normal' }} data-figure={f.key} data-missing={f.missing ? 'true' : undefined}>
							{pending ? '…' : f.value}
						</dd>
					</div>
				))}
			</dl>
			<div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 8 }}>
				{chips.map((chip) => (
					<span key={chip.key} style={styles.chip(TONE_EDGE[chip.tone])} title={chip.tooltip ?? undefined} data-chip={chip.key}>
						{chip.label}
					</span>
				))}
				<span style={{ ...styles.small, marginLeft: 'auto' }} aria-live="off">
					{stale ? 'last known values' : stats.status === 'loading' && stats.view !== null ? 'Refreshing…' : (asOf ?? '')}
				</span>
				<details style={styles.small}>
					<summary style={{ cursor: 'pointer' }}>Charts</summary>
					<StatsCharts rows={documents} dialect={dialect} />
				</details>
			</div>
		</section>
	);
}

export default StatsStrip;
