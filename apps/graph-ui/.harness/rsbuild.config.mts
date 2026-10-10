import { defineConfig } from '@rsbuild/core';
import { pluginReact } from '@rsbuild/plugin-react';

// Throwaway visual/perf harness for the graph canvas (never committed, never shipped).
export default defineConfig({
	plugins: [pluginReact()],
	source: { entry: { index: './.harness/harness.tsx' } },
	html: { title: 'graph canvas harness' },
	output: { distPath: { root: process.env.HARNESS_OUT ?? './.harness/dist' }, assetPrefix: 'auto', cleanDistPath: true },
});
