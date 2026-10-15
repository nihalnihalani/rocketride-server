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
// VECTOR-UI — UploadList (one row per dropped file)
// =============================================================================
//
// Each row: the path, a progress bar while bytes are sent, and the row's
// words (uploads.ts uploadLabel) — "Uploading… 40%", "Processing…",
// "7 chunks added", or a sentence saying why it was not added. The words
// carry the whole message; the colour of the status mark only repeats it.
// What the engine said about a failure is one click away, not in the row.
// Above the rows, the drop's summary once it is built.
// =============================================================================

import React from 'react';
import type { CSSProperties } from 'react';
import { commonStyles } from 'shell';
import { FINISHED, uploadLabel } from '../vector/uploads';
import type { UploadRow, UploadStatus } from '../vector/uploads';

/** Props of {@link UploadList}. */
export interface UploadListProps {
	rows: readonly UploadRow[];
	/** Sentences about the latest drop. */
	notes: readonly string[];
	onClearFinished(): void;
}

const S = {
	list: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 180, overflowY: 'auto' } as CSSProperties,
	row: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', columnGap: 8, rowGap: 2, alignItems: 'center', fontSize: 12, padding: '3px 4px', borderBottom: '1px solid var(--rr-border)' } as CSSProperties,
	path: { color: 'var(--rr-text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } as CSSProperties,
	label: { color: 'var(--rr-text-secondary)', textAlign: 'right', maxWidth: 320, overflowWrap: 'anywhere' } as CSSProperties,
	bar: { gridColumn: '1 / span 2', height: 4, borderRadius: 2, background: 'var(--rr-bg-widget)', overflow: 'hidden' } as CSSProperties,
	fill: { height: '100%', background: 'var(--rr-border-focus)' } as CSSProperties,
	detail: { gridColumn: '1 / span 2', fontSize: 11, color: 'var(--rr-text-secondary)' } as CSSProperties,
	notes: { margin: '0 0 4px', paddingLeft: 16, fontSize: 12, color: 'var(--rr-text-secondary)' } as CSSProperties,
	footer: { display: 'flex', justifyContent: 'flex-end', marginTop: 4 } as CSSProperties,
};

/** The status mark's colour (the label says the same in words). */
const MARK: Partial<Record<UploadStatus, string>> = {
	done: 'var(--rr-color-success)',
	failed: 'var(--rr-color-error)',
	refused: 'var(--rr-color-warning)',
	cancelled: 'var(--rr-text-secondary)',
};

/**
 * The upload list.
 *
 * @param props - {@link UploadListProps}.
 * @returns The list, or null when empty.
 */
export function UploadList({ rows, notes, onClearFinished }: UploadListProps): React.ReactElement | null {
	if (rows.length === 0 && notes.length === 0) return null;
	const finished = rows.filter((row) => FINISHED.has(row.status)).length;
	return (
		<div>
			{rows.length > 0 && (
				<p role="note" data-component="IngestSummary" data-placeholder="" style={S.notes}>
					Not built yet: a summary of this drop and where its chunks landed on the map.
				</p>
			)}
			{notes.length > 0 && (
				<ul style={S.notes} aria-label="About the last drop">
					{notes.map((note, index) => (
						<li key={index}>{note}</li>
					))}
				</ul>
			)}
			<ul style={S.list} aria-label="Uploads">
				{rows.map((row) => {
					const label = uploadLabel(row);
					const sending = row.status === 'uploading';
					const percent = row.fileSize > 0 ? Math.min(100, Math.round((row.bytesSent / row.fileSize) * 100)) : 0;
					return (
						<li key={row.id} style={S.row} data-status={row.status}>
							<span style={S.path} title={row.path}>
								<span aria-hidden="true" style={{ color: MARK[row.status] ?? 'var(--rr-border-focus)', marginRight: 6 }}>
									●
								</span>
								{row.path}
							</span>
							<span style={S.label}>{label}</span>
							{sending && (
								<div role="progressbar" aria-label={`Uploading ${row.path}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} style={S.bar}>
									<div style={{ ...S.fill, width: `${percent}%` }} />
								</div>
							)}
							{row.detail !== null && (
								<details style={S.detail}>
									<summary>What the engine said</summary>
									{row.detail}
								</details>
							)}
						</li>
					);
				})}
			</ul>
			{finished > 0 && (
				<div style={S.footer}>
					<button type="button" style={commonStyles.buttonSecondary} onClick={onClearFinished}>
						Clear finished
					</button>
				</div>
			)}
		</div>
	);
}

export default UploadList;
