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
// VECTOR-UI — ChatPanel (the console's chat over the documents, R5)
// =============================================================================
//
// The bottom half of the console's right column. Each question shows its
// answer (safe Markdown, src/chat/Markdown.tsx) with the chunks it cites:
// "3 sources · 0.58 top", each source with "open" (the document tab at that
// chunk) and "map" (highlighted on the map), and "Why these?" (the retrieval
// debugger) when the embedding node is reachable. The thread is the app's
// own rather than the shell's chat view because each answer carries its
// sources and its links must open with rel="noopener noreferrer nofollow".
//
// The header names only the LLM node. Stub answers carry the stub's prefix
// and a "Stub LLM" mark. One question in flight; Enter asks, Shift+Enter
// adds a line, ArrowUp in an empty box recalls earlier questions.
// =============================================================================

import React, { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { EmptyState, commonStyles } from 'shell';
import type { ChatPanelProps, IChatSource } from '../contract/types';
import { useVectorChat } from '../chat/useVectorChat';
import { threadScrollKey } from '../chat/chatSession';
import type { ChatTurn } from '../chat/chatSession';
import { Markdown } from '../chat/Markdown';
import { CHAT_MAX_CHARS, summariseSources } from '../vector/chatResult';
import { showAnswerOnMap } from '../adapters/consoleActions';
import { SourcesPanel } from './SourcesPanel';
import { RetrievalDebugger } from './RetrievalDebugger';

export type { ChatPanelProps };

/** Shown when the connection has no running Chat source. */
export const NO_CHAT_SENTENCE = 'This pipeline has no running Chat source.';

/** Characters left before the counter appears. */
const COUNTER_FROM = CHAT_MAX_CHARS - 500;

const S = {
	root: { display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%', padding: '8px 10px', gap: 6 } as CSSProperties,
	head: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' } as CSSProperties,
	heading: { margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--rr-text-secondary)' } as CSSProperties,
	llm: { fontSize: 12, color: 'var(--rr-text-secondary)' } as CSSProperties,
	thread: { flex: '1 1 auto', minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 } as CSSProperties,
	question: { fontSize: 13, color: 'var(--rr-text-primary)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0 } as CSSProperties,
	who: { fontWeight: 600, marginRight: 4 } as CSSProperties,
	answer: { borderLeft: '2px solid var(--rr-border-focus)', paddingLeft: 8 } as CSSProperties,
	line: { fontSize: 12, color: 'var(--rr-text-secondary)', margin: '4px 0 0', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } as CSSProperties,
	error: { fontSize: 12, color: 'var(--rr-color-error)', margin: '4px 0 0' } as CSSProperties,
	badge: { fontSize: 11, padding: '0 6px', borderRadius: 8, border: '1px solid var(--rr-border)', color: 'var(--rr-text-primary)' } as CSSProperties,
	link: { ...commonStyles.buttonSecondary, padding: '1px 8px', fontSize: 11 } as CSSProperties,
	scope: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--rr-text-primary)' } as CSSProperties,
	composer: { display: 'flex', gap: 6, alignItems: 'flex-end' } as CSSProperties,
	textarea: { flex: '1 1 auto', minHeight: 34, maxHeight: 120, resize: 'vertical', fontSize: 13, padding: '6px 8px', borderRadius: 4, border: '1px solid var(--rr-border-input)', background: 'var(--rr-bg-input)', color: 'var(--rr-text-primary)', fontFamily: 'inherit' } as CSSProperties,
	notice: { fontSize: 12, color: 'var(--rr-text-secondary)', margin: 0 } as CSSProperties,
};

/** Props of one turn. */
interface TurnViewProps extends Pick<ChatPanelProps, 'model' | 'channels' | 'selection' | 'actions'> {
	turn: ChatTurn;
	debugging: boolean;
	onDebug(open: boolean): void;
	onStopWaiting(): void;
}

/**
 * One question and its answer.
 *
 * @param props - {@link TurnViewProps}.
 * @returns The turn.
 */
function TurnView({ turn, model, channels, selection, actions, debugging, onDebug, onStopWaiting }: TurnViewProps): React.ReactElement {
	const answer = turn.answer;
	const sources: readonly IChatSource[] = answer?.sources ?? [];
	const threshold = model.connection.dialect?.score?.threshold;
	return (
		<article aria-label={`Question: ${turn.question.slice(0, 80)}`} data-turn={turn.status}>
			<p style={S.question}>
				<span style={S.who}>You:</span>
				{turn.question}
			</p>
			{turn.scope !== null && <p style={S.line}>{`Asked about ${turn.scope.length === 1 ? '1 document' : `${turn.scope.length} documents`} only`}</p>}
			{turn.status === 'asking' && (
				<p style={S.line}>
					Waiting for the answer…
					<button type="button" style={S.link} onClick={onStopWaiting}>
						Stop waiting
					</button>
				</p>
			)}
			{turn.error !== null && (
				<div>
					<p style={turn.status === 'failed' ? S.error : S.line}>{turn.error.message}</p>
					{turn.error.detail && (
						<details style={S.line}>
							<summary>Details</summary>
							{turn.error.detail}
						</details>
					)}
				</div>
			)}
			{answer !== null && (
				<div style={S.answer} data-sources={sources.length}>
					<div style={S.line}>
						<span style={{ fontWeight: 600, color: 'var(--rr-text-primary)' }}>Answer</span>
						{answer.stub && (
							<span style={S.badge} title="Answered by the local stub LLM, not a language model">
								Stub LLM
							</span>
						)}
					</div>
					{answer.text !== '' ? <Markdown text={answer.text} /> : <p style={S.line}>The pipeline answered without text.</p>}
					<div style={S.line}>
						<span>{summariseSources(sources).line}</span>
						{typeof threshold === 'number' && <span>{`threshold ${threshold.toFixed(2)}`}</span>}
						{model.embed.enabled && (
							<button type="button" style={S.link} aria-expanded={debugging} onClick={() => onDebug(!debugging)}>
								Why these?
							</button>
						)}
					</div>
					{!answer.hasDocumentsLane && <p style={S.line}>This pipeline does not return the chunks it used, so the answer cannot cite them.</p>}
					{sources.length > 0 && <SourcesPanel sources={sources} score={model.connection.dialect?.score ?? null} onOpen={(source) => actions.openDocument(source.objectId, source.chunkId)} onShowOnMap={(keys) => showAnswerOnMap(selection, actions, turn.question, keys)} />}
					{debugging && <RetrievalDebugger model={model} channels={channels} question={turn.question} topK={sources.length} answerSources={sources} onClose={() => onDebug(false)} />}
				</div>
			)}
		</article>
	);
}

/**
 * Ask questions over the connection's documents.
 *
 * @param props - The frozen props (src/contract/types.ts).
 * @returns The panel.
 */
export function ChatPanel(props: ChatPanelProps): React.ReactElement {
	const { model, channels, selection, actions, scope, onClearScope } = props;
	const chat = useVectorChat(props);
	const [draft, setDraft] = useState('');
	const [recall, setRecall] = useState(-1);
	const [debugging, setDebugging] = useState<number | null>(null);
	const thread = useRef<HTMLDivElement>(null);
	const turns = chat.state.turns;
	const scrollKey = threadScrollKey(turns);

	// Scroll to the end when a question is posted and again when its answer (often much taller) arrives.
	useEffect(() => {
		const element = thread.current;
		if (element && element.scrollHeight > element.clientHeight) element.scrollTop = element.scrollHeight;
	}, [scrollKey]);

	const available = model.chat.enabled && channels.chat !== null;
	const llm = model.nodes.llmName;

	/** Send the draft. */
	const ask = (): void => {
		if (chat.state.asking || draft.trim() === '') return;
		chat.send(draft);
		setDraft('');
		setRecall(-1);
	};

	/**
	 * Enter asks; Shift+Enter is a new line; ArrowUp/ArrowDown in an empty or recalled box walk the history.
	 *
	 * @param event - The key event on the question box.
	 */
	const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
		if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
			event.preventDefault();
			ask();
			return;
		}
		const history = chat.history();
		if (event.key === 'ArrowUp' && history.length > 0 && (draft === '' || recall >= 0)) {
			event.preventDefault();
			const next = Math.min(recall + 1, history.length - 1);
			setRecall(next);
			setDraft(history[next]);
		} else if (event.key === 'ArrowDown' && recall >= 0) {
			event.preventDefault();
			const next = recall - 1;
			setRecall(next);
			setDraft(next >= 0 ? history[next] : '');
		}
	};

	return (
		<section style={S.root} aria-label="Chat">
			<div style={S.head}>
				<h2 style={S.heading}>Chat</h2>
				{llm !== null && <span style={S.llm}>{`Answers by ${llm}`}</span>}
			</div>
			{!available ? (
				<EmptyState title="Chat is not available" description={model.chat.reason ?? NO_CHAT_SENTENCE} />
			) : (
				<>
					<div ref={thread} style={S.thread} role="log" aria-label="Questions and answers" aria-live="off">
						{turns.length === 0 && <p style={S.notice}>Ask a question; the answer cites the stored chunks it used.</p>}
						{turns.map((turn) => (
							<TurnView key={turn.id} turn={turn} model={model} channels={channels} selection={selection} actions={actions} debugging={debugging === turn.id} onDebug={(open) => setDebugging(open ? turn.id : null)} onStopWaiting={chat.stopWaiting} />
						))}
					</div>
					{scope !== null && scope.length > 0 && (
						<div style={S.scope}>
							<span>{`Asking about ${scope.length === 1 ? '1 document' : `${scope.length.toLocaleString('en-US')} documents`} only`}</span>
							<button type="button" style={S.link} onClick={onClearScope}>
								Ask about all documents
							</button>
						</div>
					)}
					{chat.state.notice !== null && <p style={S.notice}>{chat.state.notice}</p>}
					<div style={S.composer}>
						<textarea
							style={S.textarea}
							aria-label="Ask about these documents"
							placeholder="Ask about these documents…"
							value={draft}
							maxLength={CHAT_MAX_CHARS}
							rows={2}
							onChange={(event) => {
								setDraft(event.currentTarget.value);
								setRecall(-1);
							}}
							onKeyDown={onKeyDown}
						/>
						<button type="button" style={commonStyles.buttonPrimary} disabled={chat.state.asking || draft.trim() === ''} onClick={ask}>
							{chat.state.asking ? 'Asking…' : 'Ask'}
						</button>
					</div>
					{draft.length > COUNTER_FROM && <p style={S.notice}>{`${draft.length.toLocaleString('en-US')} of ${CHAT_MAX_CHARS.toLocaleString('en-US')} characters`}</p>}
				</>
			)}
		</section>
	);
}

export default ChatPanel;
