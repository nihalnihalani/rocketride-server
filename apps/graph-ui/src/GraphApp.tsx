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
// GRAPH-UI - MAIN APP
// =============================================================================
//
// Scaffold root: declares the two-column shell layout and an empty client area.
// The connections landing, workbench documents, schema sidebar and canvas are
// added by the feature slices that follow; this file only proves the remote
// loads, registers and renders inside the shell.
// =============================================================================

import React from 'react';
import type { ShellAppProps } from 'shell';
import { AppLayout, EmptyState } from 'shell';
import { GraphIcon } from './icons';
import { styles } from './styles';

/**
 * Graph Explorer - client area.
 *
 * @param _props - Shell-injected props (unused; the connection comes from hooks).
 */
const GraphApp: React.FC<ShellAppProps> = (_props) => {
	return (
		<AppLayout showStatus>
			<div style={styles.root}>
				<EmptyState icon={<GraphIcon />} title="Graph Explorer" description="Browse the graphs your pipelines already reach." />
			</div>
		</AppLayout>
	);
};

export default GraphApp;
