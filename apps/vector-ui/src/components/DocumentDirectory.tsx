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
// VECTOR-UI — DOCUMENT DIRECTORY (R3: every document by its path, with its trash button)
// =============================================================================
//
// Renders the auto-pager's rows (vector/documents.ts) as folder groups in a
// hand-windowed list (fixed 28 px rows, only the visible window mounted), so
// 5,000 documents scroll smoothly without a windowing library. The filter is
// client-side over what is loaded. Rows can be checked to remove several at
// once; removing always goes through the console's confirmation.
// =============================================================================

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from 'shell';
import type { Availability, IDocumentItem } from '../contract/types';
import type { IRemoveTarget } from '../vector/confirm';
import { buildGroups, directoryHeading, filterItems, filterSummary, pagerFooter, pagerProgressText } from '../vector/documents';
import type { IDirectoryGroup, IDirectoryRow, IPagerState } from '../vector/documents';
import { EMPTY } from '../vector/wording';
import { ChevronIcon } from '../icons';
import { FOCUS_RING, styles } from '../styles';
import DocumentRow from './DocumentRow';

/** The height of every row of the list (the windowing depends on it). */
export const ROW_HEIGHT = 28;

/** Rows rendered above and below the visible window. */
const OVERSCAN = 12;

/** Props for the {@link DocumentDirectory} component. */
export interface IDocumentDirectoryProps {
	pager: IPagerState;
	selectedId: string | null;
	writes: Availability;
	onSelect(item: IDocumentItem): void;
	onRemove(targets: IRemoveTarget[]): void;
	onLoadMore(): void;
	onRetry(): void;
}

/** One line of the flattened list. */
type Line = { kind: 'group'; group: IDirectoryGroup; collapsed: boolean } | { kind: 'row'; row: IDirectoryRow };

/**
 * A document as the remove dialogs need it.
 *
 * @param item - The document.
 * @returns The target.
 */
export function targetOf(item: IDocumentItem): IRemoveTarget {
	return { objectId: item.objectId, path: item.path, chunks: item.chunks };
}

/**
 * The directory.
 *
 * @param props - {@link IDocumentDirectoryProps}.
 * @returns The panel element.
 */
export function DocumentDirectory({ pager, selectedId, writes, onSelect, onRemove, onLoadMore, onRetry }: IDocumentDirectoryProps): React.ReactElement {
	const [filter, setFilter] = useState('');
	const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
	const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
	const [scrollTop, setScrollTop] = useState(0);
	const [height, setHeight] = useState(400);
	const viewport = useRef<HTMLDivElement>(null);

	// Measure the list's viewport (never allocate for a 0x0 box: keep the last size).
	useEffect(() => {
		const el = viewport.current;
		if (!el || typeof ResizeObserver === 'undefined') return undefined;
		const observer = new ResizeObserver(() => {
			if (el.clientHeight > 0) setHeight(el.clientHeight);
		});
		observer.observe(el);
		return () => observer.disconnect();
	}, []);

	// A checked document that is no longer listed (removed, or a new listing) is unchecked.
	useEffect(() => {
		if (checked.size === 0) return;
		const listed = new Set(pager.rows.map((r) => r.objectId));
		const kept = [...checked].filter((id) => listed.has(id));
		if (kept.length !== checked.size) setChecked(new Set(kept));
	}, [pager.rows, checked]);

	const matches = useMemo(() => filterItems(pager.rows, filter), [pager.rows, filter]);
	const groups = useMemo(() => buildGroups(matches), [matches]);
	const lines = useMemo<Line[]>(() => {
		const out: Line[] = [];
		for (const group of groups) {
			const isCollapsed = collapsed.has(group.key);
			out.push({ kind: 'group', group, collapsed: isCollapsed });
			if (!isCollapsed) for (const row of group.rows) out.push({ kind: 'row', row });
		}
		return out;
	}, [groups, collapsed]);

	const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
	const last = Math.min(lines.length, Math.ceil((scrollTop + height) / ROW_HEIGHT) + OVERSCAN);
	const progress = pagerProgressText(pager);
	const footer = pagerFooter(pager);
	const summary = filterSummary(pager, filter, matches.length);
	const checkedItems = pager.rows.filter((r) => checked.has(r.objectId));

	const toggle = (key: string): void => {
		const next = new Set(collapsed);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		setCollapsed(next);
	};
	const toggleCheck = (id: string): void => {
		const next = new Set(checked);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		setChecked(next);
	};

	let empty: string | null = null;
	if (pager.rows.length === 0 && pager.status === 'done') empty = EMPTY.noDocuments;
	else if (pager.rows.length === 0 && pager.status === 'error') empty = EMPTY.unreachable(pager.error?.headline ?? 'the store did not answer.');
	else if (pager.rows.length > 0 && matches.length === 0) empty = EMPTY.noMatch(filter.trim());

	return (
		<section aria-label="Documents" style={{ ...styles.panel, flex: 1 }}>
			<div style={styles.panelTitle}>
				<span>Documents</span>
				<span style={{ ...styles.small, fontWeight: 400, textTransform: 'none', letterSpacing: 0, marginLeft: 'auto' }}>{pager.status === 'idle' ? '' : directoryHeading(pager)}</span>
			</div>
			<div style={{ display: 'flex', gap: 8, padding: '8px 12px', alignItems: 'center' }}>
				<input type="search" value={filter} placeholder="Filter paths…" aria-label="Filter documents by path" style={styles.input} onChange={(event) => setFilter(event.target.value)} />
			</div>
			{(summary || progress) && (
				<div style={{ ...styles.small, padding: '0 12px 6px' }} role="status">
					{summary ?? progress}
				</div>
			)}
			{checkedItems.length > 0 && (
				<div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '0 12px 8px' }}>
					<span style={styles.small}>{`${checkedItems.length} selected`}</span>
					<Button small variant="danger" disabled={!writes.enabled} title={writes.reason ?? undefined} onClick={() => onRemove(checkedItems.map(targetOf))}>
						Remove selected
					</Button>
					<Button small variant="ghost" onClick={() => setChecked(new Set())}>
						Clear
					</Button>
				</div>
			)}
			<div ref={viewport} style={{ flex: 1, minHeight: 0, overflowY: 'auto', position: 'relative' }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
				{empty !== null ? (
					<div style={{ ...styles.small, padding: '16px 12px' }}>{empty}</div>
				) : pager.status === 'loading' && pager.rows.length === 0 ? (
					<div style={{ ...styles.small, padding: '16px 12px' }}>Loading documents…</div>
				) : (
					<div role="list" aria-label="Stored documents" style={{ height: lines.length * ROW_HEIGHT, position: 'relative' }}>
						{lines.slice(first, last).map((line, offset) => {
							const index = first + offset;
							const top = index * ROW_HEIGHT;
							if (line.kind === 'group') {
								return (
									<div key={line.group.key} style={{ position: 'absolute', top, left: 0, right: 0, height: ROW_HEIGHT }}>
										<button type="button" aria-expanded={!line.collapsed} onClick={() => toggle(line.group.key)} style={{ display: 'flex', alignItems: 'center', gap: 4, width: '100%', height: ROW_HEIGHT, padding: '0 8px', background: 'none', border: 'none', color: 'inherit', font: 'inherit', fontSize: 12, fontWeight: 700, cursor: 'pointer', textAlign: 'left', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} onFocus={(event) => (event.currentTarget.style.outline = FOCUS_RING)} onBlur={(event) => (event.currentTarget.style.outline = 'none')}>
											<span style={{ width: 12, height: 12, flex: 'none', transform: line.collapsed ? 'none' : 'rotate(90deg)' }}>
												<ChevronIcon />
											</span>
											{line.group.label}
										</button>
									</div>
								);
							}
							const item = line.row.item;
							return (
								<div key={item.objectId} style={{ position: 'absolute', top, left: 0, right: 0 }}>
									<DocumentRow row={line.row} selected={item.objectId === selectedId} checked={checked.has(item.objectId)} writes={writes} onSelect={() => onSelect(item)} onToggleCheck={() => toggleCheck(item.objectId)} onRemove={() => onRemove([targetOf(item)])} />
								</div>
							);
						})}
					</div>
				)}
			</div>
			{footer && (
				<div style={{ ...styles.small, padding: '6px 12px', borderTop: '1px solid var(--rr-border)', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
					<span>{footer.text}</span>
					{footer.loadMore && (
						<Button small variant="secondary" onClick={onLoadMore}>
							Load more
						</Button>
					)}
					{footer.retry && (
						<Button small variant="secondary" onClick={onRetry}>
							Retry
						</Button>
					)}
					{footer.caveat && <span style={{ flexBasis: '100%' }}>{footer.caveat}</span>}
				</div>
			)}
		</section>
	);
}

export default DocumentDirectory;
