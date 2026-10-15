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
// VECTOR-UI — ExportMenu (CSV, JSON and PNG of what is on screen)
// =============================================================================
//
// A menu of the host's export items: each one's rows (CSV with RFC 4180
// quoting and a guard for cells starting with = + - @, or JSON with
// schema_version 1) or picture (PNG), built only when chosen and handed to
// the browser as a download named
// vector-explorer_<collection>_<kind>_<yyyymmdd-hhmm>.<ext>. Nothing is sent
// anywhere; exports never carry vectors, tokens, hosts or node settings.
//
// Mounted in its host with its frozen props; until the feature is built it
// renders "Not built yet".
// =============================================================================

import React from 'react';
import type { ExportMenuProps } from '../contract/types';

export type { ExportMenuProps };

/**
 * ExportMenu: not built yet.
 *
 * @param _props - The frozen props (src/contract/types.ts).
 * @returns A note saying so.
 */
export function ExportMenu(_props: ExportMenuProps): React.ReactElement {
	return (
		<span role="group" aria-label="Export" data-component="ExportMenu" data-placeholder="">
			<span role="note" style={{ color: 'var(--rr-text-primary)', fontSize: 11.5, whiteSpace: 'nowrap', padding: '2px 6px', border: '1px dashed var(--rr-border)', borderRadius: 6 }}>
				Not built yet: export as CSV, JSON or PNG.
			</span>
		</span>
	);
}

export default ExportMenu;
