import React, { useCallback, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import GraphCanvas from '../src/canvas/GraphCanvas';
import { assignLabelColors } from '../src/graph/colors';
import { collapseNode, dismissNodes, expandNode, modelFromResult } from '../src/graph/model';
import { collectEntities } from '../src/graph/results';
import { entitiesOf, generateGraph, node, rel } from '../tests/support/generate';
import type { IGraphModel } from '../src/graph/model';
import dark from '../../../packages/shell/public/themes/dark.json';
import light from '../../../packages/shell/public/themes/light.json';
import rrLight from '../../../packages/shell/public/themes/rocketride-light.json';
import rr from '../../../packages/shell/public/themes/rocketride.json';

const themes: Record<string, Record<string, string>> = { dark, light, 'rocketride-light': rrLight, rocketride: rr };
const params = new URLSearchParams(location.search);
const themeName = params.get('theme') ?? 'light';
for (const [k, v] of Object.entries(themes[themeName] ?? light)) document.documentElement.style.setProperty(k, String(v));
document.body.style.background = 'var(--rr-bg-default)';
document.body.style.color = 'var(--rr-text-primary)';
document.body.style.fontFamily = 'sans-serif';
document.body.style.margin = '0';

const N = Number(params.get('nodes') ?? 120);
const R = Number(params.get('rels') ?? N * 2);
const SEED = Number(params.get('seed') ?? 7);
const g = generateGraph({ nodes: N, relationships: R, seed: SEED, parallel: 0.08, selfLoops: 0.02 });
const entities = entitiesOf(g.nodes, g.relationships);
(window as unknown as { __log: string[] }).__log = [];

function App(): React.ReactElement {
	const [model, setModel] = useState<IGraphModel>(() => modelFromResult(entities, Number(params.get('limit') ?? 300)));
	const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
	const [focused, setFocused] = useState<string | null>(null);
	const [hint, setHint] = useState<{ centerId: string; newIds: string[] } | null>(null);
	const [status, setStatus] = useState('');
	const [announced, setAnnounced] = useState('');
	const colors = useMemo(() => assignLabelColors(g.nodes.flatMap((n) => n.labels)), []);
	const captions = useMemo(() => new Map<string, string>(), []);
	const logRef = useRef((window as unknown as { __log: string[] }).__log);
	const log = (m: string): void => { logRef.current.push(m); };
	const doExpand = useCallback((id: string) => {
		// Synthetic neighbours (the harness has no engine).
		const fresh = Array.from({ length: 30 }, (_, i) => node(`${id}-x${i}-${Date.now() % 1000}`, ['Tag'], { name: `new ${i}` }));
		const rels = fresh.map((f, i) => rel(`${id}-xr${i}-${Date.now() % 1000}`, 'EXPANDED', id, f.id));
		const outcome = expandNode(model, id, entitiesOf([model.nodes.get(id)!, ...fresh], rels));
		setModel(outcome.model);
		setHint({ centerId: id, newIds: outcome.addedNodes });
		setAnnounced(`Expanded: ${outcome.addedNodes.length} new neighbours`);
	}, [model]);
	return (
		<div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
			<div style={{ padding: 8, fontSize: 12, borderBottom: '1px solid var(--rr-border)', display: 'flex', gap: 12, alignItems: 'center' }}>
				<span id="stats">{model.nodes.size} nodes / {model.relationships.size} rels | selected {selected.size} | focus {focused ?? '-'} | layout {status}</span>
				<button onClick={() => focused && doExpand(focused)}>expand focused</button>
				<button onClick={() => focused && setModel(collapseNode(model, focused).model)}>collapse focused</button>
				<button onClick={() => focused && setModel(dismissNodes(model, [focused]))}>dismiss focused</button>
				<span id="live" aria-live="polite">{announced}</span>
			</div>
			<div style={{ flex: 1, minHeight: 0 }}>
				<GraphCanvas
					model={model}
					colors={colors}
					captions={captions}
					selected={selected}
					focusedId={focused}
					seedKey={`seed-${SEED}`}
					expandHint={hint}
					onFocus={setFocused}
					onInspect={(id) => { log(`inspect ${id}`); setAnnounced(`Inspector opened for ${id}`); }}
					onToggleSelect={(id) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}
					onExpand={doExpand}
					onCollapse={(id) => setModel((m) => collapseNode(m, id).model)}
					onDismiss={(id) => setModel((m) => dismissNodes(m, [id]))}
					onFindPath={() => log('find-path')}
					onClearSelection={() => setSelected(new Set())}
					onHelp={() => log('help')}
					announce={setAnnounced}
					onLayoutStatus={(s) => { setStatus(s.state === 'fallback' ? `fallback:${s.reason}` : s.state); log(`layout ${JSON.stringify(s)}`); }}
				/>
			</div>
		</div>
	);
}
createRoot(document.getElementById('root')!).render(<App />);
void collectEntities;
