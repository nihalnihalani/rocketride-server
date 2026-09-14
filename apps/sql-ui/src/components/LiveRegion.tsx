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
// SQL-UI — LIVE REGION (one polite announcer for the whole app)
// =============================================================================

import React, { useSyncExternalStore } from 'react';
import type { CSSProperties } from 'react';
import { getAnnouncement, subscribeAnnouncements } from '../a11y/announce';

// =============================================================================
// STYLES
// =============================================================================

/**
 * Visually hidden but readable: clipped to a 1px box rather than
 * `display: none` or `visibility: hidden`, both of which remove the element
 * from the accessibility tree and would silence it.
 */
const hidden: CSSProperties = {
	position: 'absolute',
	width: 1,
	height: 1,
	margin: -1,
	padding: 0,
	border: 0,
	overflow: 'hidden',
	clip: 'rect(0 0 0 0)',
	clipPath: 'inset(50%)',
	whiteSpace: 'nowrap',
};

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * The app's single polite live region. Mounted once by `SqlApp`; every
 * `announce()` call anywhere in the app lands here.
 *
 * The text is rendered inside a child KEYED BY REVISION. Announcing the same
 * sentence twice would otherwise leave the DOM text unchanged and the live
 * region silent; keying by revision replaces the node, which is the mutation
 * assistive technology actually watches for.
 *
 * @returns The live region element.
 */
export const LiveRegion: React.FC = () => {
	const announcement = useSyncExternalStore(subscribeAnnouncements, getAnnouncement, getAnnouncement);
	return (
		<div style={hidden} aria-live="polite" aria-atomic="true" role="status">
			<span key={announcement.revision}>{announcement.text}</span>
		</div>
	);
};

export default LiveRegion;
