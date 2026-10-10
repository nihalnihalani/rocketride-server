# Round 3 review ledger — asclearuc's ten notes (2026-09-11)

Devil's-advocate triage (review-triage-da, Fable) — all ten claims VALID at the PR heads; two flagged as understated/partial:
- #1612 otel dependency: CI log of run 34488937607 (Ubuntu job 102914502670) shows `test_otel_mapper.py` 46 PASSED (sdk present transitively)
  but `test_otel_setup.py` ENTIRELY SKIPPED (`could not import 'opentelemetry.exporter.otlp.proto.http'`) → setup.py (transport-security
  guard, no-redirect session) has zero CI coverage on the approved head. Fix must be proven by the run log at the new head (no `SKIPPED …:47`).
  Traps: `--pytest-preinstall` only reaches `server:setup-pip`; the `test` extra is never installed in CI; `depends()` does not consume
  `constraints.lock` (do not cite the lock as proof); `importorskip` must go.
- #1607 pull_request_target: flipping the `if:` alone ships a green job that still posts nothing — under that event the checkout is the base
  branch, so the diff step compares base with itself. Acceptable shapes: (a) flip + real README recipe (head checkout by
  `github.event.pull_request.head.sha`, `persist-credentials: false`, never `install-from` the head checkout, pwn-request trade-off stated) or
  (b) keep the `if:` and delete option 3. Engineer chose (a); verify-1607 runs the security review; fall back to (b) if not clean.
- #1581: DA would keep the `json_arg` kwarg for hunk parity with #1612. LEAD DECISION: keep the engineer's removal — every pair of the trio
  already conflicts in `main.py` at the subparser anchors, so the helper hunk never bought an auto-merge; with #1581 not touching the helper
  there is no conflicting hunk in either landing order (develop's helper is unchanged if #1581 lands first; if #1612 lands first, #1581's
  default call still works). One PR (#1612) modifying the helper beats two.
- #1489: DA warns pure option 2 is dishonest in the canonical `prompt → context_optimizer → llm_*` pipeline (the prompt node writes into
  `question.context`, which the optimizer never trims). Engineer's commit: honest full-prompt verdict + measured overhead subtraction +
  README stating plainly that instructions/examples/context/goals are counted but never trimmed ("shorten them upstream, or raise
  max_context_tokens"). LEAD DECISION: accept option 2 + explicit documentation (asclearuc offered option 2 as acceptable); the reply to
  asclearuc names the prompt→optimizer case so the limitation is visible. README's generated Dependencies line is NOT hand-edited (regenerated
  by `nodes:docs-generate` on develop); `constraints.lock` untouched (CI compile-only notice on PRs; pin `tiktoken==0.13.0` satisfies the bound).
- Dismissal-on-push confirmed: `ReviewDismissedEvent`s on #1607/#1581/#1612 at 2026-09-10 14:24:50–14:25:12Z, actor = author, no message,
  previousReviewState APPROVED, seconds before the CI runs — branch protection's stale-approval rule. CHANGES_REQUESTED reviews are NOT
  dismissed by pushes (dsapandora's on #1489 survived two pushes). Cost of this round: asclearuc's four fresh approvals will be dismissed;
  the user chose to push anyway. One push per PR, everything batched.
- #683: OPEN, MERGEABLE, BLOCKED, CI OK at head, merge-tree clean vs `3626e659` (13 commits behind; develop touched only `data_conn.py`,
  `task_engine.py`, `credentials.json` on paths #683 depends on — no conflict; re-run `gen-credentials.mjs --check` after the next develop
  merge). Three CHANGES_REQUESTED stand (asclearuc 07-29; joshuadarron 07-21 never re-reviewed; dsapandora 09-07 withdrawn in prose, state
  never dismissed). Residual: asclearuc's real-engine scoring-run acceptance criterion. Legit local options (not done this round): add the
  exact reproduction recipe to `docs/develop/README-cobalt-testing.md:253-254`; note that `llm_ollama` on develop would give a real
  engine-hosted scoring run without a paid credential. No push and no new comment on #683 this round (asclearuc's 07-29 process note:
  no re-review pings until a blocking item is actually answered).
- Cross-PR: every pair of #1607/#1581/#1612 conflicts in the same six files (`CHANGELOG.md`, `docs/README-python-client.md`,
  `packages/client-python/docs/index.md`, `cli/commands/__init__.py`, `cli/main.py`, `cli.mdx`) — each inserts its block at the same anchors;
  whichever lands first forces the other two to merge develop and hand-resolve those six. CODEOWNERS (`* @jmaionchi @Rod-Christensen
  @stepmikhaylov`, `/.github/ @kwit75`) names none of the approvers — the likely reason `mergeStateStatus` stays BLOCKED despite APPROVED.
