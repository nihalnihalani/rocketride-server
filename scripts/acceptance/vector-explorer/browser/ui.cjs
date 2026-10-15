// =============================================================================
// MIT License
// Copyright (c) 2026 Aparavi Software AG
// =============================================================================

/*
 * Everything the browser lanes look for in Vector Explorer, in one place: the
 * console (lane_vector.cjs) and the map (lane_vector_map.cjs). Wording comes
 * from the app's design and its own wording modules; a change of wording in
 * the app is a change here, nowhere else.
 *
 * The map draws its points and marks on a canvas, so what a lane cannot read
 * from text it reads from data attributes on the PointCanvas root element
 * (MAP.attr). Counts, indices and overlaps are plain decimal numbers, or ''
 * when there is nothing (e.g. no point focused); flags are '1'/'0'; the mode
 * and the layout are the words listed beside them.
 */
'use strict';

const CONSOLE = {
	launcher: 'Open Vector Explorer',
	openConsole: [/^Open console$/i, /^Open documents$/i, /^Open$/i],
	statsDocuments: /Documents\s*\n?\s*([\d,]+)/,
	directoryCount: /([\d,]+)\s+documents/,
	chunksAdded: /([\d,]+)\s+chunks?\s+added/,
	replace: /Replace existing/,
	chatBox: /Ask about these documents/i,
	askButton: /^Ask$/,
	sourceOpen: /^open$/i,
	trash: (p) => `Remove ${p} from the database`,
	removeConfirm: 'Remove document',
	cancel: 'Cancel',
	loading: /Loading documents…/,
	readOnly: /Read-only/,
	logout: 'Log out',
	signIn: /sign in/i,
	consoleTab: /^Console$/,
	mapTab: /^Map$/,
};

const MAP = {
	// The PointCanvas root carries the number of points it drew and the state of its marks.
	canvas: '[data-points]',
	attr: {
		points: 'data-points', // points drawn
		mode: 'data-mode', // 'detailed' | 'light'
		layout: 'data-layout', // the layout shown: 'pca' | 'neighbour-graph' | 'tsne'
		star: 'data-star', // '1' while a query star is drawn
		rays: 'data-rays', // rays drawn from the star (to the true top-k)
		links: 'data-links', // neighbour links drawn from the selected point
		chunkPath: 'data-chunk-path', // points on the chunk path drawn
		selected: 'data-selected', // index of the inspected point, '' for none
		focused: 'data-focused', // index of the keyboard focus, '' for none
		selection: 'data-selection', // points in the lasso selection
		overlapPca: 'data-overlap-pca', // kNN overlap of the PCA layout (quality.knnOverlap, k=15)
		overlapLayout: 'data-overlap-layout', // kNN overlap of the last refined layout
	},
	toolbar: 'Map controls',
	samplePicker: /^(Sample|Points)\b/,
	lightOption: /light/i,
	detailedOption: /detailed/i,
	layoutPicker: /^Layout\b/,
	layoutOption: { pca: /^PCA$/, graph: /^Neighbour graph$/, tsne: /^t-SNE/ },
	cancel: /^Cancel$/,
	queryBox: /question on the map/i,
	run: /^Run$/,
	lasso: /^Lasso$/,
	fit: /^Fit$/,
	table: /^Table$/,
	tooltip: '[role="tooltip"]',
	inspector: 'Selected chunk',
	inspectorEmpty: /Click a point or use the arrow keys/,
	neighbourList: 'Nearest chunks in the collection',
	openDocument: /^Open document$/,
	showChunkPath: /Show chunk path on map/i,
	tabs: { duplicates: /^Duplicates$/, outliers: /^Outliers$/, selection: /^Selection$/ },
	duplicatesList: 'Near-duplicate pairs',
	outliersList: 'Outliers',
	selectionCount: /([\d,]+)\s+(?:points?|chunks?)\s+selected/i,
	tableCaption: /Points of the sample/,
	tableRows: /Rows\s+([\d,]+)\s*[–-]\s*([\d,]+)\s+of\s+([\d,]+)/,
	inspectPoint: (i) => `Inspect point ${i + 1}`,
	next: /^Next$/,
	legend: 'Map legend',
	nativeGraph: (backend) => new RegExp(`neighbour graph computed by ${backend}`),
	layoutNotBetter: /Neighbour layout did not improve on PCA/,
	layoutCancelled: /Layout cancelled/,
	layoutBusy: /Laying out…/,
	tsneLimit: /1,000/,
	announcement: (i, n) => new RegExp(`Point ${(i + 1).toLocaleString('en-US')} of ${n.toLocaleString('en-US')}\\b`),
	defaultSample: 1000,
	largeSample: 2000,
	tsneMax: 1000,
};

module.exports = { CONSOLE, MAP };
