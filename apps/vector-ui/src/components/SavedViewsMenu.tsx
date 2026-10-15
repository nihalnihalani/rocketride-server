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
// VECTOR-UI — SavedViewsMenu (the map toolbar's Views menu)
// =============================================================================
//
// Save the current view under a name, list, apply and delete views of this
// connection (in memory, at most 20, gone on sign-out). Applying draws the
// sample again with the view's seed and scope and restores its selection
// by key; never a token or a vector is kept.
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { SavedViewsMenuProps } from '../contract/types';

export type { SavedViewsMenuProps };

/**
 * SavedViewsMenu: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function SavedViewsMenu(_props: SavedViewsMenuProps): React.ReactElement {
	return (
		<span role="group" aria-label="Views" data-component="SavedViewsMenu" data-placeholder="">
			<span role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 11.5, whiteSpace: 'nowrap', padding: '2px 6px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: saved views of the map.
			</span>
		</span>
	);
}

export default SavedViewsMenu;
