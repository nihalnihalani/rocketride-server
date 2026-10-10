## Summary

- Adds two experimental nodes that make pipeline evaluation a pipeline step: **`dataset_cobalt`** (source, `_source → questions`) loads a golden dataset from JSON/CSV/JSONL or inline items and attaches each item's reference answer as `Question.metadata['expected']`; **`eval_cobalt`** (filter, `answers → answers`) scores each answer against that reference with one of six evaluators (similarity, llm_judge, custom, relevance, grounding, format) and emits a companion score answer carrying score, pass/fail and reasoning.
- Adds the plumbing that makes the reference survive the pipeline: a `metadata` dict on `Question`/`Answer` in the Python SDK, a shared `ai.common.utils.merge_metadata` helper, and its use in `ChatBase.chat()`, `LLMBase.writeQuestions` and the `prompt` node — which previously rebuilt the question and silently dropped it, scoring every item 0.0.
- Adds a 231-test harness under `nodes/test/cobalt/` (230 pass, 1 needs `OPENAI_API_KEY`), including a cross-node regression test that wires the real nodes together and asserts on the end-to-end score, plus the `eval` docs category, catalog rows, the credentials-catalog entry, and `docs/README-cobalt-testing.md`.

## Type

feature (two new nodes) + a behaviour fix in the `prompt` node + a public SDK schema addition.

## Testing

- [x] Tests added or updated
- [x] Tested locally
- [x] `./builder test` passes — CI run [34492100993](https://github.com/rocketride-org/rocketride-server/actions/runs/34492100993) on the current head `3dc37c65`: `Build / Ubuntu 22.04`, `Build / Windows Server 2022` and `Build / macOS (ARM64)` all green, `Ruff`, `gitleaks` and `Shell API contract` green, `CI OK` (job 100954315240) success. The Ubuntu leg's `nodes` pytest session collects all 217 `test/cobalt` ids (no `FAILED`/`ERROR` among them), the 13-test cross-node hop suite and `test_sys_modules_guard.py`, and ends **4257 passed, 241 skipped**. The one commit on top of that head, `1e6a43a4`, changes only `nodes/test/cobalt/conftest.py` (`sys.path` order, see below); its own run starts on push.

Run locally on `3dc37c65` (2026-09-10; the 2026-09-07 run on `e64642b5` is unchanged except where noted), from the repo root unless noted:

```
# 225 collected: 223 passed, 2 skipped
#   (skips: test_eval_cobalt_integration.py:170 needs basalt-ai-cobalt installed,
#           test_eval_cobalt_integration.py:192 needs OPENAI_API_KEY for llm_judge)
cd nodes && python -m pytest test/cobalt -q

# 13 passed — the cross-node regression suite on its own
cd nodes && python -m pytest test/cobalt/test_pipeline_metadata_hop.py -q

# 376 passed — services.json contract checks, incl. the two new nodes
cd nodes && python -m pytest test/test_contracts.py -q

# 2 passed — the new public schema fields
PYTHONPATH=packages/client-python/src python -m pytest packages/client-python/tests/test_question_schema.py -q

# exit 0 — the credentials-catalog gate added in 210c9c7f
node nodes/scripts/gen-credentials.mjs --check

# clean — 35 changed .py files (ruff 0.15.0 locally; the CI Ruff job is the authority)
ruff check <changed .py> && ruff format --check <changed .py>
# 32 commits scanned, no leaks
gitleaks detect --config .gitleaks.toml --redact --log-opts=upstream/develop..HEAD
node --check packages/docs/scripts/lib/gather.js
```

The cobalt suites need no `PYTHONPATH` — `nodes/test/cobalt/conftest.py` sets `sys.path` itself. As of `1e6a43a4` it does so the way conventions §6 asks: `nodes/src/nodes` is removed from `sys.path` and re-inserted at position 0 (the form `nodes/test/text_output/test_instance.py` established for #1687), so a same-named package in another test directory can never shadow a node; `nodes/test/cobalt` itself is still appended with a duplicate guard, and `nodes/test` stays off the path. Behaviour is unchanged: `test/cobalt` together with `test/test_sys_modules_guard.py` is 220 passed, 2 skipped, with `test_test_root_is_not_on_sys_path` passing and no `sys.modules` leaks reported — identical to the pre-change baseline.

`nodes/test/test_sys_modules_guard.py::test_node_packages_resolve_under_src_nodes` fails outside the engine interpreter with `ModuleNotFoundError: No module named 'engLib'` (it imports `text_output`, which imports `engLib`); it passes in CI under the engine interpreter (run 33848511535, Ubuntu leg). This PR touches neither that test nor `text_output`.

## Checklist

- [x] Commit messages follow [conventional commits](https://www.conventionalcommits.org/)
- [x] No secrets or credentials included — the `apikey` default is `""` and `examples/cobalt-evaluation.pipe` uses `${ROCKETRIDE_OPENAI_KEY}`
- [ ] Wiki updated (if applicable) — n/a
- [x] Breaking changes documented (if applicable) — none; `Question.metadata` / `Answer.metadata` are additive with a `{}` default

## Synced with develop

`bac83ff8` merges `upstream/develop` @ `65a2e133` into the branch (a merge, not a rebase, as @asclearuc asked on 2026-07-29 so that review anchors and previously cited SHAs stay valid; no existing commit was rewritten). Four files conflicted — `packages/ai/src/ai/common/chat.py` (#1683), `packages/ai/src/ai/common/llm_base.py` (#1780), `packages/ai/src/ai/common/utils/__init__.py`, `packages/client-python/src/rocketride/schema/question.py` — and each resolution is the union of develop's change and this PR's change; the per-file detail is in [the 2026-09-04 status comment](https://github.com/rocketride-org/rocketride-server/pull/683#issuecomment-5537593378). `develop` has since moved on to `0788b9c4`; `git merge-tree --write-tree upstream/develop HEAD` against it is still clean.

A second sync merge, `17ab8565`, followed: `develop` advanced to `973cd9b4` (#1823, `ThinkTruncatedError` handling in `ChatBase.chat`), which touches the same import block and json-parse arm this branch edits. Resolved as a union — develop keeps its `ThinkTruncatedError` import and its dedicated `except` arm, this branch keeps its `merge_metadata` import and both calls — so the branch is now level with the current `develop` tip and `git merge-tree --write-tree upstream/develop HEAD` is clean.

Commits since the last review round, in order (`git log upstream/develop..HEAD`, sync onwards):

| Commit | Subject |
| --- | --- |
| `bac83ff8` | Merge upstream/develop into feat/cobalt-pipeline-evaluation-consolidated (sync 2026-09-04) |
| `e7280cbc` | fix(nodes): drop the non-standard eval_cobalt test key and stub turn_usage |
| `68507c36` | chore(credentials): catalog the eval_cobalt judge-LLM key |
| `7c228f44` | test(client-python): add the MIT header to the Question metadata test |
| `d87f81b6` | docs(cobalt): correct the testing guide's scope and link it from the index |
| `46e2776e` | docs(nodes): add the Cobalt nodes to the changelog |
| `17ab8565` | Merge upstream/develop into feat/cobalt-pipeline-evaluation-consolidated (sync 2026-09-04, second) |
| `1e6a43a4` | test(cobalt): move nodes/src/nodes to the front of sys.path in conftest |
| `d1e8b16a` | fix(nodes): guard only the import in the Cobalt transforms fallback |
| `a22ac72c` | chore(deps): declare the Cobalt driver once for the tests to follow |
| `e64642b5` | test(cobalt): drive examples/cobalt-evaluation.pipe from the file itself |

**Head: `e64642b5`.** In brief, what those fixes are for:

- `68507c36` — `gen-credentials.mjs --check` (`210c9c7f`, inside `Shell API contract`) post-dates this PR's previous green run and `eval_cobalt`'s `eval.apikey` had no catalog entry. Added as *Cobalt Evaluator*, `required: false` (only the `llm_judge` profile reads it), field title stating it is the judge LLM provider key, not a Cobalt/Basalt key. `--check` exits 0; the job is green.
- `e7280cbc` — `test_pipeline_metadata_hop.py` stubs `ai.common.llm_adapter.turn_usage`, which develop's `llm_base.py` now imports; the non-standard `"tests"` key is dropped from `eval_cobalt/services.json` (the harness key is `test`: 0 of the 183 `services*.json` files on develop use `tests`, 71 use `test`; its three cases are covered verbatim by `test_eval_cobalt.py`); `format_check.py` uses the tuple-form `startswith`.
- `7c228f44` — MIT header on `packages/client-python/tests/test_question_schema.py`. It was 16 of the 19 `.py` files in that directory carrying the header; it is now 17 of 19.
- `d87f81b6` — `docs/README-cobalt-testing.md` no longer claims the `experiments/` suites gate CI or score real pipeline output (they score simulated outputs from the `mock_rocketride_client` fixture, and no workflow gates on them); it points at #1581 for the runner that does, and is now linked from `docs/README.md`.
- `46e2776e` — one `CHANGELOG.md` `[Unreleased] → ### Added` line.
- `d1e8b16a` — the Cobalt transforms fallback guarded more than the import, so a genuine error inside the transform was swallowed as a missing dependency. Only the import is guarded now.
- `a22ac72c` — `basalt-ai-cobalt` was declared in two places that could drift; the test copy now follows the node's declaration.
- `e64642b5` — the cross-node tests wired the same chain as the example but from items re-typed in the test file, leaving the example free to drift into a shape no test covers — the gap that let the reference-plumbing break survive four rounds. They now read `examples/cobalt-evaluation.pipe` and drive the graph it declares, through the node's own config resolver, the real `DatasetLoader`, `scanObjects` and `renderObject`. Eight tests, including an adversarial control (a wrong answer must score below threshold) and a check that no prompt the example sends contains the reference answer. Removing the single `merge_metadata` call at `nodes/src/nodes/prompt/IInstance.py:69` fails exactly the two tests that assert the reference survives every hop and that each item clears its threshold.
- `1e6a43a4` — the conftest `sys.path` change described under Testing.

Non-required jobs on the same push, for completeness: `Compile universal node constraints` (run 33848511362) passed and emitted its lockfile notice — `basalt-ai-cobalt` and `scikit-learn` are not in `nodes/src/nodes/constraints.lock`, so the regenerated lock differs (291-line diff); this PR does not modify the lockfile, and the notice says a follow-up PR regenerates it on merge. `check-externals (PR)` (run 33848511349) passed and installed `basalt-ai-cobalt==0.2.3` with no drift warning. CodeRabbit has been paused on this PR since 2026-04-18 and has posted nothing since 2026-04-29; it will not review the commits since then unless someone posts `@coderabbitai resume`.

## Known interactions and limitations

- **Depends on #1992 for the example pipeline to behave.** `fix/RR-1985-prompt-preventdefault` inserts `self.preventDefault()` in `nodes/src/nodes/prompt/IInstance.py` at the same anchor where this PR inserts its `merge_metadata` call (`IInstance.py:69`, right after the `for q in question.questions:` loop in `writeQuestions`). Without it the framework also forwards the untouched incoming question, so `llm_openai` answers twice and `eval_cobalt` emits two score answers per dataset item. The two changes are complementary and the textual conflict resolves by keeping both — merge first, then `preventDefault`. I'd suggest landing #1992 first, and I will re-merge on top.
- **#2084** (`feat/RR-1410-chat-grounding-enforcement`) also rewrites `prompt.open()`; the resolution there is the union of the two resets.
- `eval_cobalt` emits **two answers per input** on the answers lane (the original, plus the score answer). Documented in `nodes/src/nodes/eval_cobalt/README.md`; downstream 1:1 consumers will double-count. Flagged by @joshuadarron — still a product decision open to maintainers.
- **Agent nodes drop `Question.metadata`** — `ai/common/agent/agent.py` builds a fresh `Question(role=...)` from the transcript, so an evaluation pipeline routed through an agent scores 0. Tracked in **#1748** (open).
- **TypeScript SDK divergence**: `Question.ts` / `Answer.ts` have no `metadata` field yet. Split with @asclearuc's agreement; tracked in **#1747** (open). Additive TS fields are contract-floor-safe, so it can land independently.
- **No harness `test` block on either node**, deliberately. The dynamic runner always wires the node under test downstream of a `webhook` (`nodes/test/framework/pipeline.py`); `eval_cobalt`'s only input lane is `answers`, which a webhook cannot produce without a live LLM upstream, and **none of the 8 `_source`-lane services on develop has a `test` block** either — a source cannot sit downstream of the webhook the harness builds. So neither node is instantiated by the engine in `nodes:test`; the 217 cobalt tests run against stubs. Happy to write one if a maintainer can point at a shape that would work.
- **No icon.** Neither `dataset_cobalt` nor `eval_cobalt` ships an `icon` `.svg` sibling (conventions §2.5), so both render with the core `unknown.svg` fallback in the UI. Not CI-gated; I will add monochrome icons if maintainers want them in this PR rather than a follow-up.
- **No live-run evidence.** @dsapandora asked for non-zero `cobalt_score` output from a real run of `examples/cobalt-evaluation.pipe`. I have no live LLM key and cannot produce it; if it is required to close that item, it needs someone who can. That is the one review thread still open.
- **Branch name predates the `RR-<issue>` naming ruleset** (14241334). Renaming the head of a five-month-old PR would orphan it and every review anchor on it, so it is left as is; the linked issue is #1644.
- `nodes/test/cobalt/` holds both nodes' tests in one shared directory rather than `nodes/test/<node_name>/`; deferred with maintainers on 2026-07-30.

## Linked Issue

Closes #1644

Follow-ups already filed: #1747 (TypeScript SDK metadata), #1748 (agent nodes drop metadata).



<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

* **New Features**
  * Added a Cobalt Dataset source for loading inline or file-based evaluation data with filtering, sampling, and slicing.
  * Added a Cobalt Evaluator supporting similarity, relevance, grounding, formatting, custom, and LLM-judge scoring with configurable thresholds.
  * Added evaluation results with scores, pass/fail status, and reasoning.
  * Added metadata propagation between questions and answers without exposing reference data in prompts.
  * Added an example end-to-end Cobalt evaluation pipeline.

* **Documentation**
  * Added setup, configuration, evaluator, and testing documentation for Cobalt features.

<!-- end of auto-generated comment: release notes by coderabbit.ai -->


## Sync and review fixes (2026-09-10)

- `d8ff8f9e` merges `upstream/develop` @ `d5e38780` (2026-09-08; one `CHANGELOG.md` conflict — both lines kept) and `e1f06b4f` merges `upstream/develop` @ `f9a25cbb` (2026-09-10) — merge commits, as asked on 2026-07-29; no existing commit was rewritten. develop's docs restructure moved the developer docs under `docs/develop/`, so the one conflict (`docs/develop/README.md` "Further Reading") was resolved by keeping develop's sibling links and re-adding this PR's link; `docs/README-cobalt-testing.md` moved to `docs/develop/README-cobalt-testing.md` to follow the restructure (its one reference, `nodes/test/cobalt/cobalt.toml`, updated). `docs/develop/README-nodes.md` auto-merged with the two catalog rows intact.
- `56072ad9` addresses the three CodeRabbit Major threads of 2026-09-07, each with a regression test: `dataset_cobalt` now clears the template's questions for every dataset item and appends the item text only when it is non-empty (an item with empty text no longer emits the incoming template prompt); `eval_cobalt` copies the incoming answer's metadata onto the synthetic score answer so scores join to their dataset item by key rather than by answer order (documented in the node README's *Output* section); the experiments' `evaluators` shim now points at `nodes/src/nodes` instead of a nonexistent `nodes/nodes/src/nodes`.
- `3dc37c65` — develop's new icon-manifest gate (`nodes/test/test_icons.py`, #1815) failed the first post-merge CI run for exactly these two services; both nodes now ship a co-located icon (`dataset-cobalt.svg`, `eval-cobalt.svg`) declared in `services.json`. `pytest nodes/test/test_icons.py` passes.
- Local: `pytest nodes/test/cobalt` → 230 passed, 1 skipped (`OPENAI_API_KEY`); the same modules in reversed order pass; `ruff check` / `ruff format --check` clean.
- Still outstanding, as asked on 2026-07-29: a real-engine run of `examples/cobalt-evaluation.pipe` with a model credential recording per-item `cobalt_score`. The example-driven offline tests prove the metadata hop and score 1.0/1.0/1.0 with the reference present and below threshold without it, but the engine-hosted run needs an engine build and a credential this environment does not have.
