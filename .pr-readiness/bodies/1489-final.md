## Summary

- Adds `context_optimizer`, a `questions` → `questions` filter node that fits an LLM request into the model's context window by budgeting tokens across the system prompt, question, retrieved documents and conversation history — truncating on sentence boundaries, keeping the highest-scoring documents that fit, and compacting the middle of the history. Requests that already fit pass through unchanged, with no extra model call.
- Resolves context-window sizes from the **live LLM catalog** (`modelTotalTokens` on the `preconfig` profiles of the sibling `llm_*` nodes, maintained by `tools/sync_models`), with a refreshed hand-maintained table as fallback and `manual` mode as the explicit override.
- Ships the node package, its co-located icon and README, a 125-test unit suite, a `services.json` `test` block for the dynamic harness, plus the `docs/README-nodes.md` catalog row and the `CHANGELOG.md` entry.

## Type

feature (new node)

## Testing

- [x] Tests added or updated
- [x] Tested locally
- [x] `./builder test` passes — CI run [34487046212](https://github.com/rocketride-org/rocketride-server/actions/runs/34487046212) on the current head `90b8e247`: Ruff, gitleaks, Shell API contract, Build on Ubuntu 22.04 / Windows Server 2022 / macOS (ARM64) and `CI OK` all succeeded. The Ubuntu Build job ran `nodes:test` with `4196 passed, 240 skipped, 0 failed`, covering the `test/context_optimizer` suite on that head and both `test_dynamic` cases (`context_optimizer:services:test1:auto`, `context_optimizer:services:test2:ci_tiny`) — so the `services.json` block has now run through the real harness on all three runners, not only in my local replay. `3a43ea1a` and `b3fdf78a` (below) add further unit tests on top of that head, and run 33926033046 on `b3fdf78a` is green on every check.

Locally verified on `90b8e247` (macOS, Python 3.12) — the unit suite is 171 tests (+1 real-tiktoken-only skip); the table below is the 2026-09-04 run, the 2026-09-10 additions are listed under *Sync and review fixes* further down:

| Command | Result |
| --- | --- |
| `ruff check nodes/src/nodes/context_optimizer nodes/test/context_optimizer` | `All checks passed!` |
| `ruff format --check …` (ruff 0.16.6) | `7 files already formatted` |
| `pytest test/context_optimizer -q` (cwd `nodes/`, real `tiktoken` 0.14.0) | `125 passed` |
| `pytest test/context_optimizer -q` (stubbed `tiktoken`, the unit-test interpreter's normal path) | `125 passed` |
| `node nodes/scripts/gen-credentials.mjs --check` | exit 0 — `catalog matches detected credential-shaped fields` |
| `node scripts/audit-icons.mjs` | `util-text.svg` resolves; no new warnings |
| `gitleaks detect --config .gitleaks.toml --log-opts upstream/develop..HEAD` | `4 commits scanned`, `no leaks found` |

The unit suite imports the real `rocketlib` / `ai` and the native `engLib`, so outside the built engine interpreter it needs those on `PYTHONPATH` (plus an `engLib` stub); the numbers above come from that setup. The `services.json` dynamic cases were additionally replayed by hand against real `tiktoken` before CI ran them: question truncated to 95 chars and still `beginsWith` `alpha`; documents `[doc-priority, doc-followup]`; history compacted to 2 entries with the `Earlier conversation summarized` marker.

## Checklist

- [x] Commit messages follow [conventional commits](https://www.conventionalcommits.org/)
- [x] No secrets or credentials included
- [ ] Wiki updated (if applicable)
- [x] Breaking changes documented (if applicable) — none, this is an additive node

## Sync with develop (2026-09-04)

Rebuilt linearly on `upstream/develop` @ `0788b9c4` (`develop`'s tip at the time of writing; the branch is 0 behind / 4 ahead and `git merge-tree` reports no conflicts). The branch previously carried four merge commits from develop, which CONTRIBUTING.md:109-114 asks us not to do; a straight commit-by-commit replay also conflicted on intermediate commits that touched files this PR does not change. The branch is now **four commits**, and the tree differs from `develop` by exactly the node package, its tests, and the two docs files (12 files, +3003 / -0):

| Commit | Subject |
| --- | --- |
| `74981296` | `feat(nodes): add context_optimizer token-budget node` |
| `f3922319` | `docs(nodes): list context_optimizer in the node catalog and changelog` |
| `820ce6b8` | `fix(nodes): keep every question entry and hold every context_optimizer budget` |
| `a61e8483` | `fix(nodes): tokenize provider-scoped model ids with the right encoding` |
| `9b4cfcce` | Merge upstream/develop (`f9a25cbb`) into the branch — 2026-09-10, no conflicts |
| `90b8e247` | `fix(nodes): context_optimizer reads the model catalog through the engine registry and budgets unknown models conservatively` |
| `7410ab07` | `fix(nodes): return an empty history when the budget cannot cover role overhead` |

**Dropped in the rebuild**

- The four merge commits (`b562dc36`, `6d8a151b`, `2b160b1d`, `8c843663`).
- `37c1942e` — a `.github/workflows/_build.yaml` fork-PR `ROCKETRIDE_APIKEY` fallback. Upstream now hard-codes `ROCKETRIDE_APIKEY: MYAPIKEY` there (`_build.yaml:283`), so the hunk was already a no-op and only produced a replay conflict. **This PR no longer touches `.github/` at all.**
- `2ad344eb`'s `packages/client-typescript/tests/RocketRideClient.test.ts` hunk — a revert of an earlier out-of-scope change, net zero against the merge base and since reshaped upstream. Two of its `IInstance.py` / `optimizer.py` hunks are carried forward: the user-role summary placeholder and the unknown-model warning. The third — the multi-question drop warning asked for on #527 — is **superseded**, not carried: CodeRabbit's review on this PR showed that dropping the extra `QuestionText` entries loses data the downstream embedding and store nodes rely on, so `1f612031` preserves every entry under one shared query budget instead. Nothing is dropped, so there is no drop warning left to emit.
- `5ab3105e` / `2bc7e051` / `12577c19` / `3b8ae612` — the add-then-remove of `nodes/test/mocks/{tiktoken,json5}` and `nodes/test/guardrails/__init__.py`. Net zero; **no compute library is mocked under `nodes/test/mocks/`**, since that directory is prepended to every engine subprocess via `ROCKETRIDE_MOCK` and would shadow the real library engine-wide. The stubs live inside `test_all.py` and are installed only when `importlib.util.find_spec` says the real library is absent.
- `eb20aa7d` — an empty CI-retrigger commit.

**Picked up while rebasing**

- `MODEL_LIMITS` refresh + live catalog lookup — see below.
- `classType` `transform` → `text`. `transform` is not in `packages/docs/scripts/lib/gather.js` `NODE_CATEGORIES`, so the docs sidebar filed the node under *Other*; `text` matches the sibling `questions`/`text` nodes that share this icon.
- Co-located `util-text.svg`. Since `488d076b` (2026-08-07) the engine resolves `icon` **relative to the services.json directory** and logs `Icon : **** MISSING` when it is absent (`services.cpp:1680-1691`); the old basename-keyed lookup that used to find another node's copy is gone, so the file is now functionally required rather than cosmetic. Duplicating the SVG per node is the established convention (`scripts/audit-icons.mjs` rule 4).
- `docs/README-nodes.md` catalog row and a `CHANGELOG.md` `[Unreleased] / Added` line, as every node PR merged since July has done.
- `nodes/test/context_optimizer/test_all.py` now uses the remove-then-`insert(0)` `sys.path` idiom that `test_sys_modules_guard.py::test_node_packages_resolve_under_src_nodes` expects (`39bc5090`).

**Deliberately not changed**

The `docs/README-nodes.md` "121 node directories → 151 services" sentence and the lane-ontology produced/consumed counts are left alone. Both are already stale on develop (137 directories / 183 `services*.json` today), so bumping them by one would propagate a wrong number, and they are the exact lines that would collide with #2139 (still open, deletes this file) and #683.

**CI checks that ran on this branch for the first time**

Before today the only CI run this branch had was 2026-07-08 (`eb20aa7d`), which predates two of the current jobs. Both have now run on `1f612031`:

1. **Shell API contract** (`d8b5813e`, gating `CI OK`; includes the credentials-catalog check added in `210c9c7f`) — **success** in run 33854833165. No catalog entry was needed; `context_optimizer.max_context_tokens` matches the credential regex by name but `scanFields` skips it because its `type` is `number`.
2. **Compile universal node constraints** (`f41afb5e`, triggered because `nodes/src/nodes/context_optimizer/requirements.txt` is new) — **success** in run 33854833037. `tiktoken` was already pinned at `0.13.0` in `nodes/src/nodes/constraints.lock` via `langchain-openai` / `llama-index-core` / `mistral-common`, so no new pin was needed.

**check-externals (PR)** (advisory) also succeeded, in run 33854832813; the lazily-imported `tiktoken.get_encoding` / `encoding_for_model` symbols exist in the pinned version.

## CodeRabbit review rounds

**2026-09-04 round on the rebased head — six threads, all fixed in `1f612031`.** Each was reproduced before it was changed, and each has a regression test that fails when the fix is reverted. CodeRabbit confirmed five of the six in-thread; the sixth (NaN, item 3) got a rate-limit banner instead of a confirmation, so its fix is described in the thread reply.

1. **Multi-entry questions were being dropped.** `writeQuestions` collapsed `question.questions` to a single entry and warned. Downstream, `embedding_transformer` writes an embedding per entry and `store_elasticsearch` reads per-entry embedding metadata, so the dropped entries lost real data. Every entry is now preserved: a single entry takes the optimizer's result directly, several entries share the query budget via the new `ContextOptimizer.truncate_each_to_budget` (each keeps a slice proportional to its own token cost). This supersedes the #527 "warn on drop" ask — see above.
2. **Provider-scoped ids skipped the fallback table.** `openai/gpt-5` resolved to `DEFAULT_MODEL_LIMIT` (128 000) with an unknown-model warning wherever the sibling `llm_*` nodes are not deployed, instead of the table's 400 000. `resolve_model_limit` now walks one candidate tuple (full id, then bare name) through the catalog *and* the table, preserving full-id precedence in both.
3. **NaN budget percentage crashed `optimize()`.** `document_budget_pct=float('nan')` survived validation and blew up in `allocate_budget` with `cannot convert float NaN to integer`. `_parse_pct` now clamps NaN to `0.0` with a warning, ahead of the range checks.
4. **`truncate_to_budget` could exceed its budget at sentence boundaries.** Joining sentences can cost more than the sum of their parts (a sentence starting with a digit does not absorb the joining space), so the sentence-boundary path overshot by a token. The joined candidate is now re-measured and falls through to the token-level cut when it does not fit; exact-fit sentence behaviour is unchanged.
5. **`summarize_history` under-reserved the summary placeholder.** `[Earlier conversation summarized]` is 5 tokens but `[Earlier conversation summarized: N messages omitted]` is 10, so the substitution overshot. The placeholder is now built at its worst case (`max_omitted = len(messages) - 1`) before the reservation is measured. The same sweep caught the adjacent `len(messages) == 1` early return ignoring the `role + 4` framing overhead; that is accounted for the same way. One visible consequence: at the handful of budgets where the old code overshot, the result is now the truncated first message with no summary marker rather than first + placeholder over budget. This commit fixed the placeholder overshoot but **not** the sub-overhead edge described in the next section — that needed `3a43ea1a`.
6. **A per-call `model` override used the wrong encoding.** `optimize(model=...)` applied the override's token *limit* while counting through the instance model's encoding. `encoding_name_for_model` now resolves an arbitrary id without touching the instance cache, `optimize()` derives the encoding from the effective model and threads it through every count, and the resolved encoding is reported as `metadata['encoding']`.

**2026-07-08 outside-diff note — fixed in `3a43ea1a`.** CodeRabbit's review body of 2026-07-08 02:10Z carried one *Outside diff range* comment on `summarize_history` that was posted after that round's inline threads had been answered, and it stayed unanswered through the rebuild. It was still real on `1f612031`: every returned message costs `count_tokens(role) + 4` before any content, so when `max_tokens` is below that floor both the `len(messages) == 1` branch and the `budget_for_recent <= 0` fallback computed a negative `content_budget`, got `''` back from `truncate_to_budget`, and returned a 5-token message anyway (reproduced: 1 message at `max_tokens=2` → 5 tokens; 3 messages at `max_tokens=3` → 5 tokens). Both branches now carry CodeRabbit's proposed guard, `if content_budget < 0: return []` (`optimizer.py:635-639` and `:674-677`), and the docstring states the empty-list case. `< 0` rather than `<= 0` on purpose: a budget exactly equal to the overhead still affords one empty-content message costing exactly the budget. Sweeping budgets `0..8` over both shapes after the fix: `0-4` → `[]`, `5+` → one message costing at most the budget, zero over-budget results. `TestHistorySummarization::test_budget_below_role_overhead_returns_empty` covers both branches across every budget below the floor plus the boundary; neutralising the guard fails it with `assert [{'role': 'user', 'content': ''}] == []`. With this commit `truncate_to_budget` and `summarize_history` hold their documented budget on every path I can construct; before it, that statement was not true at the tightest history budgets.

**2026-09-04 16:14Z outside-diff review.** CodeRabbit posted three further findings on `optimizer.py`. Two are fixed in `b3fdf78a`: a provider-scoped id such as `openai/gpt-5` resolved the gpt-5 *context window* through the bare-name fallback while `encoding_name_for_model()` kept the prefix, so the override table missed, `tiktoken.encoding_for_model()` raised and the count silently fell back to `cl100k_base` — the gpt-5 window measured with the gpt-4 tokenizer; and a non-string `model_name` reaching `resolve_model_limit()` raised on `rsplit()` during `beginGlobal`, so it is now coerced to the documented default with a warning. The third (single quotes for the quote-character literals at `optimizer.py:234`/`:238`) I rebutted: those lines already read `elif char == '"':` — single-quoted literals containing one double-quote character, which is the house style ruff enforces. A PR comment answering all three is posted.

The three `ci_tiny` cases in `services.json` were replayed against all of the above and are byte-identical.

## Where the context window comes from (`MODEL_LIMITS` refresh)

@asclearuc left a "note to address in future" on #527 about the hand-coded `MODEL_LIMITS` table. develop now has a better answer, and this push uses it.

`auto` mode resolves the window in three steps:

1. **The live model catalog.** Every LLM node's service definition carries `modelTotalTokens` on each `preconfig` profile, and `tools/sync_models` keeps those in step with the providers. `ContextOptimizer.model_catalog()` reads them through the engine's own registry — `rocketlib.getServiceDefinitions()` (the `{"services": …}` envelope) for the index, then `getServiceDefinition()` for each raw definition — so an installed or `--node_path`-materialised node with no sibling directories sees the same catalog the engine loaded, and it is re-read at every pipeline start. Previously it globbed the sibling `llm_*` directories once, caches the result, and covers **332 model ids** on today's develop — so `gpt-5.4` (1 050 000), `claude-sonnet-4-6` (1 000 000), `models/gemini-3.1-pro-preview` (1 048 576), `grok-4-0709` (256 000) and everything else the LLM nodes publish resolves without this node hard-coding it. A provider-scoped id also resolves under its bare name, but only when unambiguous: an unscoped profile wins (so `gpt-5` keeps llm_openai's 400 000 rather than a gateway's 128 000 re-host), and a bare name two gateways disagree about is dropped rather than silently resolved one way. `services*.json` is JSONC, so the node parses it with a small string-aware comment stripper rather than taking a `json5` dependency.
2. **`MODEL_LIMITS`**, now refreshed against that catalog and reduced to a fallback: it covers deployments where the `llm_*` nodes are not present next to this one, and it defines the abbreviated family aliases no provider actually publishes (`claude-sonnet`, `claude-opus`, `gemini-pro`, `gemini-flash`). The stale entries are gone — `claude-sonnet` was 200 000 against a catalogued 1 000 000, `gpt-5` was 128 000 against 400 000, and there were no `gpt-5.4` / `claude-*-4-6` / `gemini-3*` keys at all. `TestModelLimits::test_fallback_table_never_disagrees_with_catalog` asserts that for every id present in both, the table and the catalog state the same window (39 shared ids on `0788b9c4`, zero disagreements); it fails loudly if a `tools/sync_models` run moves one, which is the signal to refresh the table or drop the key.
3. **The conservative fallback** — the smallest window any registered chat-LLM profile or `MODEL_LIMITS` publishes (8 191 on develop today; embedding and vision windows are catalogued for lookup but never lower it), with a one-time warning naming the unresolved id. The previous optimistic 128 000 default budgeted four times a 32k model's window and made the provider reject the request.

`manual` mode sets `max_context_tokens` explicitly and bypasses all three.

I deliberately did **not** rewire the node onto `IInvokeLLM.GetContextLength()` / `GetTokenCounter()` — the engine-native channel that `summarization` and `preprocessor_llm` use. It is only reachable after `beginFilter` (see the comment in `summarization/IInstance.py:180-193`), so consuming it means restructuring this node's lifecycle, which is out of scope here. Both the node README and the class docstring name that channel as the authoritative source and `manual` mode as the escape hatch. Happy to follow up in a separate PR if maintainers want the invoke path instead of the catalog read.

`classType: ["text"]` is a judgement call — `preprocessor` would also be defensible. Easy to change if the docs owners prefer a different sidebar category.

## tiktoken and network access

Worth flagging explicitly because it affects the required Build matrix: **`tiktoken` downloads its BPE vocabulary from `openaipublic.blob.core.windows.net` the first time an encoding is requested**, then caches it on disk. Both encodings this node uses are affected — `o200k_base` for the `auto` profile (`gpt-5`) and `cl100k_base` for `ci_tiny` (`model: custom` → fallback). I confirmed this locally: a clean `TIKTOKEN_CACHE_DIR` gained both vocab files (5.2 MB) during the first test run.

The `services.json` `test` block therefore reaches a CDN inside the required Build matrix (a comment directly above that block says so), which is the same class of dependency that put `embedding_transformer` / `embedding_video` (RR-1120) and `authoritative_overlay` (`c04ebaf4`) into `conftest.py`'s `skip_nodes`. Both dynamic cases passed on all three Build runners in run 33854833165, and I have **not** pre-emptively added a skip entry because that would remove the node's only end-to-end coverage — but if maintainers want the RR-1120 policy applied here, say so and I will add `'context_optimizer'` to `skip_nodes` with the same comment style as `authoritative_overlay` in this PR. The node README documents `TIKTOKEN_CACHE_DIR` pre-seeding for air-gapped deployments.

## Notes for reviewers

- The unit suite imports the real `rocketlib` / `ai` (no core-module stubs left in `sys.modules`, per the `a438c23c` guard) and therefore needs the build interpreter; outside it, collection errors out by design. `tiktoken` / `json5` are node-runtime deps absent from the unit-test interpreter, so `test_all.py` injects deterministic in-process stubs **only** when `find_spec` reports the real library missing. The suite passes both ways (125 tests, real and stubbed).
- All six CodeRabbit review threads from the 2026-09-04 round are answered by `1f612031` and resolved; the 2026-07-08 outside-diff note is answered by `3a43ea1a`, and the three 2026-09-04 16:14Z outside-diff findings by `b3fdf78a` (two fixed, one rebutted — see above). Of the five asks carried over from #527, four are addressed on the branch as originally requested — user-role summary placeholder (`optimizer.py`), unknown-model warning, score-descending document sort, and the `MODEL_LIMITS` note answered above. The fifth, the multi-question drop warning, is **superseded**: `IInstance.writeQuestions` no longer drops the extra `QuestionText` entries, so there is nothing to warn about; every entry is kept and trimmed under one shared query budget.
- The branch name `feature/context-optimizer-node` predates the `feat/RR-<issue>-<slug>` naming rule in CONTRIBUTING.md; renaming it would close and re-target this PR, so it is left as is.

## Linked Issue

Refs #527 — this PR continues that closed PR of mine, which is where the review history lives. There is **no issue filed for this node yet**, so this PR currently has no `Closes` link; if maintainers need one before merging, tell me and I will file a scoped issue and add `Closes #<n>` here.

---

Rebase, the `MODEL_LIMITS` catalog lookup, and this description were prepared with AI assistance (Claude Code); all changes were reviewed and verified locally by me.


<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

- **New Features**
  - Added an experimental Context Optimizer node that fits requests within model context limits.
  - Automatically manages token budgets across prompts, questions, documents, and conversation history.
  - Truncates or summarizes oversized content and selects the most relevant documents.
  - Added configurable model, context-limit, and budget settings, including automatic and manual profiles.

- **Documentation**
  - Added setup and behavior documentation and catalog references for the new node.

- **Tests**
  - Added comprehensive coverage for optimization, budgeting, ranking, truncation, configuration, and lifecycle behavior.

<!-- end of auto-generated comment: release notes by coderabbit.ai -->



## Sync and review fixes (2026-09-10)

- `9b4cfcce` merges `upstream/develop` @ `f9a25cbb` (27 commits; `CHANGELOG.md` and `docs/develop/README-nodes.md` auto-merged, no conflicts). The 2026-09-04 rebuild's SHAs in the table above were unreachable after that rebuild landed on the fork; the table now lists the commits actually on the branch.
- `90b8e247` addresses the 2026-09-07 review ([discussion](https://github.com/rocketride-org/rocketride-server/pull/1489#discussion_r3950836282)): catalog discovery moves from a `__file__`-relative glob to the engine registry (see *auto* mode above), the class-level catalog cache is removed (fresh read per pipeline start, per-optimizer snapshot), and the unknown-model fallback becomes the conservative floor instead of 128 000. `README.md` describes the final contract.
- Tests: 171 passed / 1 skipped under the node's own suite; new cases drive the production registry path with the engine's real envelope shape (unwrap, envelope keys never treated as types, unusable envelopes, per-type failures, refresh without restart, no-filesystem guarantee, and the floor rules). A before/after probe of the reported scenario (node with no sibling directories, unknown model) budgets 128 000 on the previous code and 8 191 on this head.
- **Round 3 `cd5db1b1` + `30011d2f` (2026-09-11):** asclearuc approved with three inline notes; all addressed in `cd5db1b1` on top of the approved head, with the CI-only `ci_tiny` fixture recalibrated in `30011d2f` (80 → 112 tokens, 160-word over-budget question) because the honest count no longer left room for the history summary placeholder in that profile. The pass-1 "everything fits" verdict now uses the full rendered prompt: `IInstance` renders `getPrompt()` on a copy with the four budgeted fields emptied (placeholders kept so the section markup counts), counts it with the node's tokenizer plus a two-token margin for the line break after a non-empty `role`, and passes it as `optimize(overhead_tokens=...)`; budgets are allocated from `total_limit` minus that overhead, `tokens_used` includes it, and when the overhead alone fills the window every budget is 0 and the four fields are emptied with one warning. The README's "What it does" states which fields are trimmed (`role`, `questions`, `documents`, `history`) and which are only counted (`instructions`, `examples`, `context`, `goals`, markup). `tiktoken>=0.7.0,<1.0.0` (the generated constraints lock and README dependency line are left to their generators). `max_context_tokens` is parsed with `ai.common.utils.config_int` (semantics identical for this field; the local non-numeric warning is dropped). Tests: 195 tests pass under real tiktoken 0.14.0 (194 plus one tokenizer-specific case under the whitespace stub); the headline regression and 11 dependent cases fail with the old accounting. CI: [run 34602242917](https://github.com/rocketride-org/rocketride-server/actions/runs/34602242917) on `30011d2f` — `CI OK` green (17 checks passed, 4 expected skips; the earlier run on `cd5db1b1` failed only the CI-only `ci_tiny` fixture case that `30011d2f` recalibrates). dsapandora's earlier request is unchanged by this round and still needs their re-review.
