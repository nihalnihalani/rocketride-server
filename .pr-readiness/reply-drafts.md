# PR Readiness — Reply Drafts

Skeletons only, for the lead (nihalnihalani) to fill in placeholders (`[commit sha]`, `[test name]`,
`[result]`, `[revision]`) and post — **nothing in this file has been posted, and this agent made no
GitHub writes of any kind.** Drafted per the classification in `review-ledger.md`; threads that are
purely informational (author self-review notes with no reviewer ask) are explicitly called out as
needing no reply rather than given a hollow skeleton.

PRs covered: #683, #1489, #1581, #1607, #1612.

---

## PR #683 — reply drafts

### Thread #56 — dataset_cobalt/IInstance.py:72 (CodeRabbit, VALID-FIX-REQUIRED)

Addressed in [commit sha]. `q.questions = []` now runs unconditionally for every emitted item
(moved outside the `text is not None and text != ''` guard), so an item with empty dataset text no
longer leaves the incoming template's stale prompt in place → the emitted question always reflects
the current item, never a carried-over one. Verified with [new/updated test name] against
[revision] — mutation-checked by reverting the fix and confirming the test fails.

### Thread #57 — eval_cobalt/IInstance.py:152 (CodeRabbit, VALID-FIX-REQUIRED)

Addressed in [commit sha]. `eval_answer` now copies the incoming `metadata` (via `copy.deepcopy`)
onto the synthetic score answer before `setAnswer()`, so a downstream consumer can join a
`cobalt_score` to its originating dataset item by metadata rather than by answer order, which isn't
stable across fan-out or parallel workers. Verified with [new/updated test name] against [revision].

### Thread #58 — nodes/test/cobalt/evaluators/__init__.py:39 (CodeRabbit, VALID-FIX-REQUIRED)

Addressed in [commit sha]. `_NODES_DIR` now resolves to `<repo>/nodes/src/nodes` (dropped the extra
`'nodes'` path segment that produced the nonexistent `nodes/nodes/src/nodes`), so experiment test
collection under `nodes/test/cobalt/experiments/` no longer risks an import failure at that path.
Verified by running [test collection command] against [revision] and confirming `eval_cobalt`
imports cleanly.

### Top-level status comment — asclearuc (blocking items 1-3, review of 2026-07-29)

@asclearuc, status against your three blocking items on [head sha], target `develop`@[develop sha]:
(1) the `prompt`-node metadata hop is fixed and covered by `nodes/test/cobalt/test_pipeline_metadata_hop.py`
(13 tests, offline trace [result]); the one piece still open is the live-engine run with a real LLM
credential you and @dsapandora asked for — I still don't have one, so this needs someone who does.
(2) covered by the same test file. (3) the branch has drifted behind `develop` again since July
(currently [N] commits behind, [conflict status]) — resyncing before the next pass. Given your
CHANGES_REQUESTED predates all of this and was never re-reviewed, could you take another look, or
dismiss/re-submit if your position has changed?

### Top-level status comment — joshuadarron (blocking items 1-4, review of 2026-07-21)

@joshuadarron, all four blocking items from your July 21 review were addressed in
[commit shas — a0b77d52/2ffd9921] and never re-reviewed: co-located READMEs now exist for both
nodes, the dataset loader has a genuine pure-Python fallback instead of silently yielding an empty
dataset, the `file_path` description now matches `_validate_path`'s actual behavior, and the BLE001
concern turned out moot (rule isn't enabled — asclearuc confirmed independently). Could you re-review
against [head sha]?

### Top-level status comment — dsapandora (split request, withdrawn but review state unchanged)

@dsapandora, thanks again for withdrawing the split request. One housekeeping item: your Sep-7
14:56Z review is still recorded as **Changes requested** on GitHub, which is one of the things
holding `mergeStateStatus` at BLOCKED — since your 18:58Z comment says nothing from your side blocks
it, dismissing or re-submitting that review as a comment would clear the state to match. Entirely
your call.

### PR-level summary skeleton (≤250 words, for the lead to fill and post)

Head `d8ff8f9e` (26 commits behind `develop`@`f9a25cbb`, currently CONFLICTING — needs a resync
before merge). Three reviewers currently show CHANGES_REQUESTED (asclearuc 07-29, joshuadarron
07-21, dsapandora 09-07); none has re-reviewed since their stated blocking items were addressed, and
dsapandora's is additionally withdrawn in-thread but not in review state.

**Fixed since each review**: asclearuc's metadata-hop / 0.0-score bug (prompt node now forwards
`Question.metadata`; 13-test cross-node regression suite added) and multi-node coverage ask;
joshuadarron's co-located docs, silent dataset-loader no-op, and abs-path doc mismatch; three fresh
CodeRabbit Major findings from 09-07 fixed in [commit sha] — [one-line each once fixed].

**Still open — not fixable by this PR alone**: a live-engine run of `examples/cobalt-evaluation.pipe`
with a real LLM credential showing non-zero `cobalt_score`, asked by asclearuc, dsapandora and
CodeRabbit. Offline evidence (real node classes/schema, only the provider call stubbed) shows
1.0/1.0/1.0 where it previously scored 0.0/0.0/0.0, with an adversarial wrong-answer control — but
this is not a substitute for the live run and nobody in this review chain currently has a credential
to produce one.

**Test results**: [`./builder test` result / `pytest nodes/test/cobalt` result] against [revision] —
placeholder, needs the engine binary (see test-commands.md).

**Gates**: CI OK, Ruff, gitleaks, Shell API contract (credentials catalog), Compile universal node
constraints — all required; Helm/Container-scan/check-externals not required.

**Ask**: resync with develop; re-review from asclearuc and joshuadarron (both fully addressed);
someone with a live LLM credential to close the one open acceptance item.
## PR #1489 — Reply Drafts

Skeletons only — placeholders (`[commit sha]`, `[test name]`, `[result]`) for nihalnihalani (the lead) to fill in and post. Do not post as-is.

Scope note: of the 13 threads + 4 outside-diff findings catalogued in `1489-ledger.md`, only **Thread #13** is currently open and needs a genuinely new reply. Threads #1–#12 and Outside-diff-A/B1/B2/B3 are already resolved/confirmed with full technical replies already posted by the author — no new reply is drafted for those (nothing to add). Thread #9 gets an optional low-priority FYI skeleton for a sign-off gap that doesn't block anything. Rod-Christensen's top-level ask is closed (README + fixes landed) and doesn't need a reply either.

---

### Thread #13 — `optimizer.py:293`, `_CATALOG_ROOT` / optimistic empty-catalog fallback (OPEN — reply once fixed)

> Addressed in [commit sha]. The empty-catalog fallback in `resolve_model_limit()` now [defaults conservatively — e.g. errs toward a small window / requires `manual` mode when neither the live catalog nor `MODEL_LIMITS` resolves the id — replace with actual behavior] instead of the optimistic `DEFAULT_MODEL_LIMIT=128000`, so a node installed outside the `nodes/` tree (local store, `--node_path`) no longer risks budgeting 4x a small model's real window. The catalog is now read via [the engine's services-file loading path / other mechanism — replace with actual fix], not a glob relative to `__file__`, and the class-level cache [now invalidates on `sync_models` / is documented as intentionally static — replace with actual resolution]. Verified with [test name] against [revision] — reproduces the empty-catalog scenario you described and confirms the fallback no longer over-budgets.

---

### Thread #9 — `optimizer.py:383`, NaN in `_parse_pct` (RESOLVED — optional FYI, low priority, no action required)

> Flagging for the record, not reopening: CodeRabbit's confirmation on this thread never actually landed — it hit a rate limit ("31 minutes and 32 seconds") instead of confirming, even though the thread shows resolved. The fix itself (`_parse_pct` rejecting NaN via `pct != pct` before the range clamps, `optimizer.py:373-377`) has since been independently re-verified against current head and is covered by `TestNaNBudgetPercentage`. No action needed — just closing the loop in case anyone audits sign-off history on this thread later.

---

### PR summary skeleton (≤250 words, top-level comment)

> **Status update — [date]**
>
> Head: `a61e8483358e8b7ce3b7e4db2db2bf7261d401fc` (`feature/context-optimizer-node`) · Target: `develop` @ [re-check current develop tip before posting — develop moves; this review pass used `f9a25cbbd7`] · 27 commits behind / 5 ahead as of this review pass (re-check before posting), diff scoped to `nodes/src/nodes/context_optimizer/`, `nodes/test/context_optimizer/`, `docs/README-nodes.md`, `CHANGELOG.md` · merge status: [re-check `git merge-tree` / mergeable flag before posting — last known: mergeable=UNKNOWN/UNKNOWN, integrate=clean].
>
> **Fixed since the last review pass, verified against current head:**
> - All 6 CodeRabbit round-1 findings (tokenizer-from-model-name, `allocate_budget` remainder, fallback-truncation role overhead, `ci_tiny` enum leak, builtin generics, brittle log assertion).
> - All 6 CodeRabbit round-2 findings (multi-entry `QuestionText` preservation under a shared budget, `MODEL_LIMITS` bare-name fallback, NaN budget guard, sentence-truncation re-measurement, summary-placeholder worst-case reservation, effective-model encoding threading).
> - The 2026-07-08 outside-diff role-overhead guard, and two of the three 2026-09-04 16:14Z outside-diff findings (scoped-id encoding normalization, `model_name` validation) — the third (single-quote nitpick) was a false positive, confirmed no change needed.
>
> **Tests:** [N passed / M skipped: RESULT] (`nodes/test/context_optimizer` unit suite + `context_optimizer:services:test1:auto` / `test2:ci_tiny` dynamic cases). CI gates: Ruff, gitleaks, Shell API contract, Build (Ubuntu 22.04 / Windows Server 2022 / macOS ARM64), `CI OK`, Compile universal node constraints, check-externals (advisory).
>
> **Still open:** @dsapandora — the one unresolved thread (`optimizer.py:293`, empty-catalog fallback defaulting to an optimistic 128k) is now addressed in [commit sha] — could you take another pass when you have a chance? Nothing else on this PR is outstanding.
## PR #1581 — Reply drafts

All 8 review threads are currently `isResolved=True` (see ledger). Skeletons below are drafted only for threads with something still genuinely unresolved (a real, un-answered maintainer question) — not for threads that already contain a satisfying, specific closing reply. **The lead (nihalnihalani) posts these, not this session** — placeholders (`[...]`) need filling before posting.

---

### Threads needing NO new reply (context only, do not post)

- **Threads #1, #2, #4** (`runner.py:352`, `judge.py:155`, `spec.py:1`) — author's own explanatory self-review notes, no reviewer request attached, nothing to answer. No skeleton drafted.
- **Threads #5, #6, #7, #8** (the four CodeRabbit code-defect findings) — each already has, in-thread, an author reply matching the "Addressed in [commit]... verified with [test]" shape with real values (not placeholders) plus CodeRabbit's own confirmation ("✅ Review thread resolved"). Re-verified independently against current head `1b7ed669` in the ledger — all four fixes and their named tests are actually present. Posting a new reply here would be redundant. **No skeleton drafted; flagged in the ledger only because thread #5 crosses the 10-day-age threshold, not because it needs action.**

---

### Skeleton 1 — Thread #3 (`cli/commands/eval.py:36`, exit-code all-or-nothing policy)

Classification: DISAGREEMENT-FALSE-POSITIVE (deliberate, documented, tested — not a defect), but carries an explicit, twice-repeated, never-answered ask for a maintainer ruling. Post as a new reply in this thread:

> This one isn't a defect, it's the deliberate all-or-nothing exit-code policy I flagged back on [original date] and again after the rebase — spec validation still aborts the whole run with exit 2 before any network I/O, unchanged, and it's covered by [test name(s), e.g. `TestCliEval` in `test_cli_integration.py`] as of [commit sha]. What's actually still open is the call I asked for and never got: keep all-or-nothing, or switch to per-file isolation like `validate` (#1573)? @[maintainer] — could you make this one, since it's a policy choice rather than something I should decide unilaterally? Happy to implement either way once you weigh in.

---

### Skeleton 2 — PRODUCT-MAINTAINER-DECISION (dsapandora's review, databaseId=5133353026)

Not a code fix — surfaces the scope question to a maintainer rather than claiming anything is resolved. Post as a new top-level PR comment (or a reply to dsapandora's review):

> Thanks for the engineering approval, @dsapandora. The product question you raised — four new CLI subcommands (#1581, #1607, #1612, #1573) landing within about a month, sharing `cli.mdx`, `README-python-client.md`, and the subcommand registry — is the same across all four PRs, so I don't think it's mine to settle alone. @[maintainer], could you make the call on scope and landing order? Per the PR description I'd suggest #1613 → #1573 → #1581 → #1607 → #1612, but I'll rebase onto whatever order you actually merge in.

---

### Skeleton 3 — Top-level PR summary (≤250 words)

Post as a fresh top-level comment once the rebase below is done and the placeholders are filled:

> **Head:** `1b7ed6697f1f28d11aa794ae4008f9d59c596ccd` (`feat/RR-1578-eval-runner`, 9 commits) → **develop**.
>
> ⚠️ **Needs a rebase before merge.** Last synced against `develop@65a2e133` (2026-09-03), clean `git merge-tree` then. Develop has since moved ~49 commits ahead; the merge is now `CONFLICTING/DIRTY` (`integrate=CONFLICTS`). Rebasing and re-verifying `git merge-tree` before final review — flagging now so review isn't spent against a base that's about to move.
>
> **Fixes since the July review request** (commit [commit sha], each with a regression test, re-verified at current head):
> - `judge_factory` no longer orphans a started pipeline if it raises — teardown moved inside `try`/`finally` (`test_teardown_when_judge_factory_raises`).
> - `json_path` `equals` no longer conflates JSON booleans and numbers (`test_json_path_equals_does_not_conflate_bool_and_number`).
> - Judge wait now bounded by `judge_timeout` (default 300s) instead of hanging forever on a non-cancellable worker thread (`test_stalled_judge_times_out_and_pipelines_are_torn_down`, `test_default_judge_timeout_is_finite`).
> - A non-UTF-8 spec file now raises `EvalSpecError`/exit 2 instead of leaking to the generic exit-1 handler (`test_non_utf8_file_raises_spec_error`).
>
> **Tests:** [N passed / M skipped: RESULT] on [commit sha]; `ruff check` / `ruff format --check`: [RESULT].
>
> **CI gates that apply:** `CI OK` (Ruff, gitleaks, Build ×3 — Ubuntu/macOS/Windows), Shell API contract. Helm lint and container-scan skip (no `deploy/helm/**` changes; not a `pull_request`-triggered scan).
>
> **Asks for a maintainer** (not dsapandora, who already approved the engineering): (1) scope/landing-order call across #1581/#1607/#1612/#1573 — four new CLI subcommands in about a month; (2) keep the current all-or-nothing spec-validation exit-2 policy, or switch to per-file isolation like `validate`?

*(Word count of the quoted summary body, verified with `wc -w`: 240 words — under the 250-word cap.)*
## PR #1607 — Reply drafts

Scope note: all 27 review threads are `isResolved=True` and, per the ledger's per-item current-head verification, 22 of the 23 actionable threads are genuinely fixed at head (not just marked resolved) — CodeRabbit's own bot already closed those loops with its own confirmation replies, so a human re-reply from the author would be redundant noise on those. Only **one** thread still needs a human decision voiced in-thread: **Thread #19** (SHA-pinning of the self-referential `pipe-diff@develop` action ref). Drafted below, plus the required PR-level summary skeleton.

If the lead wants closing acknowledgements posted on the other 22 threads anyway (e.g. as a courtesy sweep before requesting re-review), the shared shape is: *"Confirmed fixed in [commit]. Verified at current head [file:line]; regression coverage in [test name]."* — happy to generate the other 22 on request, but they were not drafted individually here to avoid restating what CodeRabbit's own bot replies already say on each of those threads.

---

### Thread #19 reply skeleton
`PRRT_kwDOROCxS86fNJBz` — `docs/README-python-client.md` (+ same pattern in `examples/pipe-diff-example.md`, `cli.mdx`) — addressed to @kwit75 (CODEOWNER of `.github/`), cc @coderabbitai

> All three third-party `uses:` refs (`actions/checkout`, `actions/setup-python`, `marocchino/sticky-pull-request-comment`) are pinned to reviewed full commit SHAs across all three doc sites as of [commit sha]. `pipe-diff@develop` is the one ref deliberately left unpinned: the action doesn't exist on `develop` until this PR merges, so there is no reviewed SHA yet that a reader could actually use. @kwit75 — this is one of the three open questions from the [2026-09-04 status comment]: pin now to [commit sha] (documents a ref only usable after merge) and I'll update it again once a release exists, or leave `@develop` as the interim placeholder until then? Either way I'll push the update to `cli.mdx`, `README-python-client.md`, and `examples/pipe-diff-example.md` together in [commit sha] and re-ping this thread.

---

### PR summary skeleton (≤250 words)

> **Status update — rebase needed, otherwise ready**
>
> Head: `6f9199758160457114a568bb53e68d1077fa8077` (`feat/RR-1606-pipe-diff`) · Target: `develop` @ [current develop HEAD sha] · Merge-base at last sync: `65a2e133`.
>
> **Review status:** all 27 threads resolved — 23 CodeRabbit findings over 4 rounds (reverified against current head) plus 4 author self-review notes. dsapandora approved 2026-09-07 at this exact head. One open item, not a code defect: @kwit75, the `pipe-diff@develop` SHA-pinning call above, plus two related CODEOWNER questions from the 2026-09-04 status comment (in-repo composite action at all? add it to `dependabot.yml`?).
>
> **Conflict status:** now **49 commits behind `develop`**, GitHub reports `mergeable=CONFLICTING`/dirty — needs a rebase or re-merge before landing, independent of the approval. [Rebasing onto develop @ [sha] / conflicts in: [file list]].
>
> **Tests:** [N passed / M skipped: RESULT] against the rebased head (`pytest tests/test_diff_cli.py tests/test_pipediff_engine.py tests/test_pipediff_gitref.py tests/test_pipediff_reporters.py -q`; 121 passed pre-rebase at `77d212e7` — needs a fresh run).
>
> **CI gates:** Build (Ubuntu 22.04 / Windows Server 2022 / macOS ARM64), `Test`, Shell API contract, Ruff, gitleaks — green at [commit], not yet re-run post-rebase.
>
> **Re-review ask:** shares `cli.mdx`, `README-python-client.md`, and the CLI subcommand registry with #1581 (`eval`) and #1612 (`otel`) — whichever merges first forces a small re-rebase of the others. Requesting sign-off on landing order (proposed #1573 → #1581 → **#1607** → #1612) before final re-review.
## PR #1612 — reply drafts

All values below are **placeholders** for the lead (nihalnihalani) to fill and review before posting — nothing here should be posted verbatim. Where a placeholder has a known value, it is cross-referenced to `1612-ledger.md` rather than filled in directly, since the ledger's values could drift if more commits land before these are posted. Drafted for every one of the 19 actionable CodeRabbit threads (#5–#23) plus the two PRODUCT-MAINTAINER-DECISION sources and the one logistics note — even though all 23 threads currently show `isResolved=True` on GitHub, several close with CodeRabbit's own "I couldn't resolve this thread automatically, remains open" boilerplate, so a clean audit-trail confirmation is still worth having ready. Threads #1–#4 (the author's own design notes, no reviewer ask) get no draft — there is nothing to reply to.

Notation: `[sha]` = short commit SHA, `[test]` = test name, `[result]` = pass/fail count or assertion result. See `1612-ledger.md` for the ledger-verified value behind each placeholder.

---

### Threads #5–#13 (round 1, July — all ALREADY-ADDRESSED / one DISAGREEMENT / one OUTDATED-WITHDRAWN)

**Thread #5 — credentials via `--headers`/argv (docs)**
> Addressed in [sha]. The Langfuse and LangSmith recipes now export the auth value through `OTEL_EXPORTER_OTLP_HEADERS` instead of `--headers`, so a real key never lands in shell history or `ps` output. Verified with [test/manual check — base64 padding survives SDK parsing] against [revision]. Confirming this stays closed at current head; no further action needed on our side.

**Thread #6 — error-mapping doc scope**
> Addressed in [sha]. The Errors section now says a `trace.error` maps on a component **leave** event specifically (handled in `_flow_leave`), not "any flow event," matching what the mapper actually does. Verified with [test] against [revision]. Re-confirmed still accurate as of [current head sha] — no drift since the original fix.

**Thread #7 — `rrext_store` example (out of scope for this PR)**
> This line is pre-existing content this PR doesn't touch — our diff only adds the `rocketride otel` row immediately above it. The fix is tracked separately in #1613 (`rocketride store dir /`), which will land in both `docs/README-python-client.md` and `packages/client-python/docs/index.md` in one place. Keeping this PR scoped to the otel addition; closing here with the pointer to #1613 rather than duplicating the fix.

**Thread #8 — `--trace-level none` message**
> Addressed in [sha]. `none` is now special-cased: the message states flow tracing stays disabled and no FLOW events are emitted, instead of implying `none` triggers events. Verified with [test] against [revision]. Confirming still correct at current head.

**Thread #9 — `rocketlib.debug` (false positive)**
> No change made — this finding doesn't transfer to this package. `client-python`'s `pyproject.toml` declares only [websockets/aiofiles/pydantic], no `rocketlib` dependency, and `bridge.py`'s `_log()` is operator-facing stderr output that [test — e.g. a startup-failure test] asserts on directly, not debug tracing. CodeRabbit withdrew this finding and recorded a corrective learning; confirming no further action needed.

**Thread #10 — header env-var precedence**
> Addressed in [sha]. Only explicit `--headers` now becomes an exporter header set; the generic `OTEL_EXPORTER_OTLP_HEADERS` env var is left to the SDK, so signal-specific `_TRACES_HEADERS`/`_METRICS_HEADERS` keep their documented precedence. Verified with [test] against [revision]. Confirming still correct at current head.

**Thread #11 — fallback→canonical run promotion**
> Addressed in [sha]. A fallback-keyed run (`project_id|source`) is now promoted to the canonical `run_id` the first time they meet, with open spans re-stamped and a guard preventing distinct canonical runs from ever merging. Verified with [test] against [revision]. Note: the mirror-image gap (canonical state already present when the fallback arrives) was a separate finding, closed under Thread #14 — see that reply.

**Thread #12 — `trace.error` privacy gate**
> Addressed in [sha]. `trace.error` now exports only the error *signal* (status `ERROR`, bare exception event, generic description) by default; the actual message text is withheld unless `--include-content` is passed, matching the bridge's privacy-by-default contract everywhere else. Verified with [test/sentinel-scan result] against [revision]. Confirming still correct at current head — this was one of two defects flagged for explicit current-head re-verification, and it checks out.

**Thread #13 — meter provider shutdown ordering**
> Addressed in [sha]. `shutdown()` now wraps the tracer-provider shutdown in `try/finally`, so `meter_provider.shutdown()` always runs even if the tracer half raises. Verified with [test] against [revision]. Confirming still correct at current head.

---

### Thread #14 (round 1.5, July — ALREADY-ADDRESSED)

**Thread #14 — fallback absorption when canonical state already exists**
> Addressed in [sha]. This was the mirror case of Thread #11: when a canonical run already exists and a fallback-keyed run for the same (project, source) shows up later, `_absorb_fallback_run` now migrates its non-colliding pipes (re-stamped to the canonical run id) and closes any colliding ones as unclosed, rather than leaving a stranded duplicate. Verified with [test] ([N] tests passing) against [revision]. Confirming still correct at current head.

---

### Threads #15–#23 (round 2, September — all ALREADY-ADDRESSED)

**Thread #15 — credential exposure + Base64 line-wrap (docs)**
> Addressed in [sha]. Both recipes now prompt for secrets with non-echoing reads instead of carrying a placeholder for a live key, and the Langfuse Base64 command strips embedded line breaks (`tr -d '\r\n'`) since real keys exceed GNU base64's 76-character wrap. Verified by [manual/test check] against [revision]. Note for the record: this thread's last CodeRabbit reply says it "couldn't resolve automatically... remains open" — the structured `isResolved` field says otherwise as of [audit date], but flagging in case a manual close is still wanted.

**Thread #16 — redact endpoint on startup print**
> Addressed in [sha]. The startup line now always prints through `redact_endpoint()` for both `--endpoint` and the environment-resolved endpoint, stripping userinfo/query/fragment while keeping the path (the part operators actually check). Verified with [test] against [revision]. Confirming still correct at current head.

**Thread #17 — encrypted transport required (cli/main.py)**
> Addressed in [sha]. A single `validate_transport_security(config, env)` guard (shared with the `config.py:177` and `setup.py:123` threads) now refuses to start when a credential-looking header name pairs with a non-loopback cleartext endpoint, exit code 2, with `--insecure` / `ROCKETRIDE_OTEL_ALLOW_INSECURE=1` as the explicit opt-out. Verified with [test] against [revision]. Confirming still correct at current head.

**Thread #18 — asyncio signal-handler ownership**
> Addressed in [sha]. `run_bridge` no longer steals a SIGINT/SIGTERM callback the embedding event loop already owns (asyncio provides no way to give a replaced callback back, so not stealing it is the only correct fix); a new `install_signal_handlers=False` lets embedders opt out entirely. Verified with [test] (embedder's `Handle` object identical before/after) against [revision]. Confirming still correct at current head.

**Thread #19 — endpoint precedence + cleartext credentials (config.py:177)**
> Addressed in [sha], two sub-findings. Endpoint precedence: `--endpoint` is the only path to an explicit endpoint now; `OTEL_EXPORTER_OTLP_ENDPOINT` is left to the SDK so signal-specific endpoint overrides keep precedence. Cleartext credentials: covered by the same `validate_transport_security()` guard as Thread #17. Verified with [test] against [revision]; confirming still correct at current head.

**Thread #20 — no-redirect exporter session**
> Addressed in [sha]. Both OTLP/HTTP exporters now get a `requests.Session` whose `send()` forces `allow_redirects=False` (the default `True` would replay `x-api-key` to any 3xx target, since `requests` only strips `Authorization` on a cross-host redirect), probed via `inspect.signature` for exporters that predate the `session=` kwarg. Verified with [test] against [revision]. This is one of two defects flagged for explicit current-head re-verification; confirming still correct.

**Thread #21 — per-run pipe cap + LRU eviction**
> Addressed in [sha]. `MAX_TRACKED_PIPES_PER_RUN` now bounds pipes within a single run (separate from the run-count cap), evicting the least-recently-**eventful** pipe as unclosed — recency is tracked explicitly via `_touch_pipe` rather than relying on dict insertion order, since a chatty pipe must not evict a quiet-but-still-open one. Verified with [test] ([N]-pipe cap test) against [revision]. Confirming still correct at current head.

**Thread #22 — cleartext credentials in `build_providers`**
> Addressed in [sha]. `validate_transport_security(config)` is now the first statement in `build_providers`, so embedders calling it directly (not just the CLI) are covered before any exporter or worker thread exists. Verified with [test] against [revision]. Confirming still correct at current head.

**Thread #23 — tracer-provider cleanup on metric-setup failure**
> Addressed in [sha]. Metric-provider construction is now wrapped so a failure (e.g. a missing gRPC exporter package) shuts down the already-started tracer provider and its worker thread before re-raising, instead of leaking it behind a "startup failed" message. Verified with [test] (asserts `TracerProvider.shutdown` called exactly once) against [revision]. Confirming still correct at current head.

---

### PRODUCT-MAINTAINER-DECISION replies (surface, don't claim a fix)

**On dsapandora's "fourth CLI subcommand" question (review databaseId=5133352894):**
> Thanks for approving on the engineering side. On the product question you raised: this would be the fourth new subcommand landing from my open PRs (alongside #1581's `eval`, #1607's `diff`, and #1573's `validate`), all touching `cli.mdx`, `README-python-client.md`, and the subcommand registry. [Maintainer name] — happy to take direction on whether all four should land, and in what order; I'll rebase the others to resolve the shared-file conflicts once you decide. No code changes pending on this thread, just your call on scope.

**On nihalnihalani's own #616-direction question (conversation comment databaseId=5538586909, part a):**
> Flagging again for visibility since this is a standing open question rather than a code issue: is a client-side bridge over the documented `rrext_monitor` protocol the direction you want for #616, or would you rather wait for engine-native instrumentation (the approach #498 originally proposed and archived)? This PR is zero-engine-change either way, so it doesn't foreclose the native path landing later — but it's worth an explicit yes/no before merge rather than after. [Maintainer name] — your call.

**On the logistics note (part b — CLI landing order across #1573/#1581/#1607/#1613):**
> Sequencing note, not a review item: #1573, #1581, #1607, and #1613 all touch the same registration files as this PR (`cli/commands/__init__.py`, `cli/main.py`, and/or the two doc files). Whichever of these lands first, I'll rebase the rest and resolve by keeping both entries. No action needed from a reviewer here — just flagging so a maintainer can pick a landing order if they have a preference, otherwise I'll go in [PR numbers / order] as they clear review.

---

### PR summary skeleton (≤250 words, top-level comment)

> **Status update — rebased, approved on engineering, two product questions open**
>
> Head: `[head sha — 0a5c6f8c, confirm current]` · Target: `develop` @ `[develop sha — confirm current, was 65a2e133a at last rebase, 49 commits behind as of this ledger]`
>
> **Conflict status:** this branch is currently `CONFLICTING`/dirty against the live merge-base and 49 commits behind `develop` — a rebase or re-merge is needed before this can land cleanly; I'll do that as soon as the product questions below are settled, to avoid re-rebasing twice. [Confirm conflict status is unchanged / re-run `git merge-tree` before posting.]
>
> **Fixes landed across two review rounds** (round 1: July, round 2: post-rebase September) — full detail and per-thread verification in the internal ledger, headline items: fallback-run correlation (promotion + absorption, no more duplicate/stranded spans), the `trace.error` privacy gate, per-run pipe cap with LRU eviction, cleartext-credential refusal (`validate_transport_security`, one guard shared across three call sites), no-redirect OTLP/HTTP exporter sessions, signal-handler ownership (no more stealing an embedder's SIGINT/SIGTERM callback), endpoint/header env precedence left to the SDK, and endpoint redaction on stdout.
>
> **Tests:** `[N passed / M skipped: RESULT]` — otel test modules at current head; base CI matrix unaffected (otel deps are fully optional).
>
> **CI gates that apply:** Build matrix (3 OSes), Ruff, gitleaks, Shell API contract, `check-externals`. Node-constraints compile job does not trigger (no `nodes/**/requirements.txt` touched).
>
> **Re-review ask:** two product calls before merge — (1) do we want a 4th CLI subcommand given the shared-file overlap with #1573/#1581/#1607, and (2) is a client-side `rrext_monitor` bridge the right direction for #616. Engineering re-review otherwise not blocking.
