# Round 3 — one comment per PR to asclearuc (post after the thread replies are up and resolved)

Placeholders: `{HEAD}`, `{RUN}`, `{TESTS}`.

## #1612

@asclearuc — thank you for the review and the approval. You marked both notes as non-blocking, but each was worth doing, so both are addressed in `3a4c06aa` (one commit on top of the head you approved; no history rewritten):

- The opentelemetry test dependency is now declared where CI actually installs it (`packages/server/build-requirements.txt`, via `server:setup-test-deps`) plus `rocketride[otel]` in the `dev`/`test` extras, and the two guarded test modules import it unconditionally — a missing dependency now fails collection instead of skipping 1 455 lines. Worth knowing: on the head you approved, the run log shows `test_otel_setup.py` skipped entirely (the exporter was not installed), so this closes a real gap, not a theoretical one.
- `run_bridge` builds only the provider half it is missing and chains a caller-supplied `shutdown_fn` in front of the providers' shutdown (caller first, providers in a `finally`); nine regression tests, seven of which fail on the old code.

Tests: 143 otel tests pass with 0 skipped (75 in the two formerly guarded modules); with the two source files reverted, 7 of the 9 new tests fail, and without opentelemetry the two modules now fail collection (exit 2). `CI OK` is green on `3a4c06aa` ([run {RUN}](https://github.com/rocketride-org/rocketride-server/actions/runs/{RUN})), and that run's log shows the otel modules collected and passing, 0 skipped. Pushing dismissed your approval automatically — when you have a moment, could you re-stamp it? Details per note are in the thread replies.

## #1607

@asclearuc — thank you for the review and the approval. You marked all three notes as non-blocking, but each was worth doing, so all three are addressed in `05278aae` (one commit on top of the head you approved; no history rewritten):

- The sticky-comment step now runs under `pull_request_target` as well — you were right that the `if:` and the README contradicted each other. While fixing it I found a second gap: under `pull_request_target` the default checkout is the base branch, so the action was diffing base against itself; it now warns when the PR head is absent from the checkout. The README's option 3 now says plainly *not* to check out the PR head in that job (the action runs `python -m pip` and `git` inside the checkout, so PR-controlled files there are not inert) and shows the safe route for fork PRs: compute on `pull_request`, post the comment from a `workflow_run` workflow. Defence in depth: both `python` invocations in the action now run with `-I`, so the checkout can never shadow `pip` or `importlib`.
- The version comparison uses `_json_equal`, with `1 → true` / `0 → false` regression tests.
- `_md_cell` no longer doubles backslashes inside code spans (verified against cmark-gfm; Windows-path and regex tests added).

Tests: 104 pipediff tests pass; the two engine and two reporter regressions fail on the old code; YAML, `if:` expressions, `bash -n` and shellcheck are clean. `CI OK` is green on `05278aae` ([run {RUN}](https://github.com/rocketride-org/rocketride-server/actions/runs/{RUN})); the branch still merges cleanly onto develop. Pushing dismissed your approval automatically — when you have a moment, could you re-stamp it? Details per note are in the thread replies.

## #1581

@asclearuc — thank you for the review and the approval. You marked both notes as non-blocking, but each was worth doing, so both are addressed in `335d3ec0` (one commit on top of the head you approved; no history rewritten):

- `eval` takes the shared `--json [FILE]` now, through the same `Output` channel `validate` uses: bare `--json` owns stdout, `--json FILE` writes the document and keeps the human report on stdout, and `--json FILE --junit …` compose. The `json_arg` keyword this PR had added to `_add_connection_args` had no other caller here, so it is gone and the helper is byte-identical to develop again.
- `_expand_files` lives once, as `expand_file_patterns()` in `cli/utils/file_utils.py` beside `find_files()`, imported by both `eval` and `validate`, with its own tests.

Tests: 241 tests pass (216 across the eval modules, 14 validate, 9 for the shared helper, 2 live-CLI registration); with the sources reverted, 6 eval tests fail and the helper tests no longer import. `CI OK` is green on `335d3ec0` ([run {RUN}](https://github.com/rocketride-org/rocketride-server/actions/runs/{RUN})); the branch still merges cleanly onto develop. Pushing dismissed your approval automatically — when you have a moment, could you re-stamp it? Details per note are in the thread replies.

## #1489

@asclearuc — thank you for the review and the approval. You marked all three notes as non-blocking, but each was worth doing, so all three are addressed in `cd5db1b1`, followed by `30011d2f` (both on top of the head you approved; no history rewritten):

- The "everything fits" verdict now uses the full rendered prompt: the fields `getPrompt()` renders beyond the four budgeted ones (`instructions`, `examples`, `context`, `goals`) and the section markup are measured by rendering a blanked copy through `getPrompt()` itself, counted with the node's tokenizer, and subtracted from the window before budgets are allocated (your option 2, measured rather than estimated). I reproduced the original failure first with real `cl100k` tokens — a 1633-token prompt passed through a 1632-token window untouched — and the measured figure carries a two-token margin for the one line break the blanked rendering cannot see, so it always errs high. The README states which fields are trimmed and which are only counted, including the `prompt → context_optimizer` case.
- `tiktoken>=0.7.0,<1.0.0`, matching `chunker` (the generated lock and README dependency line are left to their generators, as they should be).
- `max_context_tokens` is parsed with `config_int`, semantics verified identical for this field.
- Knock-on caught by CI on `cd5db1b1`: the CI-only `ci_tiny` profile (80 tokens, tuned for the old count) could no longer fit the history summary placeholder once the markup was counted. `30011d2f` recalibrates it to 112 tokens with a 160-word over-budget question; all three fixture cases still exercise their truncation paths and pass with margin under real `cl100k` tokens.

Tests: 195 tests pass under real tiktoken 0.14.0 (194 plus one tokenizer-specific case under the whitespace stub); the headline regression and 11 dependent cases fail with the old accounting. `CI OK` is green on `30011d2f` ([run {RUN}](https://github.com/rocketride-org/rocketride-server/actions/runs/{RUN})); the branch still merges cleanly onto develop. Pushing dismissed your approval automatically — when you have a moment, could you re-stamp it? Details per note are in the thread replies.
