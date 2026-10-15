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
// VECTOR-UI — ScopeBar (the directory's filter row)
// =============================================================================
//
// The directory's path box, first, then Add condition (folder, file type,
// ingest dates, chunk counts, tables, missing first chunk) and Saved. With no
// condition it is one row, exactly the old filter row; the conditions scope
// the documents, the map, search and chat (ConsoleModel.scope).
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { ScopeBarProps } from '../contract/types';
import { styles } from '../styles';

export type { ScopeBarProps };

/**
 * The directory's filter row: the path box, and (not built yet) its conditions.
 *
 * @param props - The path box's text and its change handler.
 * @returns The row.
 */
export function ScopeBar({ text, onText }: ScopeBarProps): React.ReactElement {
	return (
		<div style={{ display: 'flex', gap: 8, padding: '8px 12px', alignItems: 'center' }} data-component="ScopeBar" data-placeholder="">
			<input type="search" value={text} placeholder="Filter paths…" aria-label="Filter documents by path" style={styles.input} onChange={(event) => onText(event.target.value)} />
			<span role="note" style={{ ...styles.small, whiteSpace: 'nowrap' }}>
				Not built yet: conditions and saved filters
			</span>
		</div>
	);
}

export default ScopeBar;
