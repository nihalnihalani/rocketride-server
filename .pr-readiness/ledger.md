# Shared work ledger (lead-maintained)
| PR | Owner | Initial remote head | Current candidate | Step | Blockers | Next action | Evidence |
|---|---|---|---|---|---|---|---|
| #683 | lead | d8ff8f9ed | 3dc37c65 PUSHED — CI OK green (16/4 skipped); 3 replies + resolutions, summary, description posted | TECHNICALLY READY — AWAITING REVIEW; external gate: real-engine scoring run (credential) | real-engine scoring evidence needs engine build + model credential | push → replies on 3 CodeRabbit threads → summary | prs/683-changes.md, validation.md |
| #1489 | lead | a61e84833 | 90b8e247 PUSHED — CI OK green (17/4 skipped), summary + description posted, re-review asked | TECHNICALLY READY — AWAITING REVIEW (dsapandora's changes-requested stands until re-reviewed) | engine-hosted run unavailable locally | verifier review → push → reply on thread PRRT_kwDOROCxS86f9NuY → summary → re-review ask | prs/1489-changes.md |
| #1612 | sdk-implementation-engineer | 0a5c6f8ce | 1d16eed5f PUSHED — CI OK green (16/4 skipped); summary + description posted | TECHNICALLY READY — AWAITING REVIEW/DECISION | develop rewrote the CLI (BaseCommand/RocketRideCLI deleted) → command ported; README-clients relocation; cli.mdx count sentence needs bump per land | verifier → lead push (last in order) | conflict-resolutions-cli.md, prs/1612-changes.md |
| #1607 | sdk-implementation-engineer | 6f9199758 | b2d6d5bda PUSHED — CI OK green (15/4 skipped); summary + re-review mention posted | TECHNICALLY READY — AWAITING REVIEW (approval predates sync) + CLI-surface product decision | same CLI rewrite | verifier → lead push (first in order) | prs/1607-changes.md |
| #1581 | sdk-implementation-engineer | 1b7ed6697 | 8e7ef7230 PUSHED — CI OK green (19/4 skipped; labeler cancelled, non-gating); summary + re-review mention posted | TECHNICALLY READY — AWAITING REVIEW + product decisions (CLI surface, exit-code policy) | same CLI rewrite | verifier → lead push (second in order) | prs/1581-changes.md |
Departed from scope during the task: #1573, #1586, #1613 merged 2026-09-08 (Leela8256); #897/#899 merged 2026-09-08 (dsapandora).

## 2026-09-10 ~16:30Z — develop tip moved; #1581 follow-up pending push

- `upstream/develop` advanced `ec44e5bb` → `bb766ae3` (one commit: #1788 `feat(nodes): add Zhipu AI GLM LLM provider node (llm_glm)`).
  `git merge-tree --write-tree bb766ae3 <head>` is CLEAN for all five current heads (#683 `3dc37c65`, #1489 `90b8e247`,
  #1607 `b2d6d5bd`, #1581 `8e7ef723`, #1612 `1d16eed5`) and for the #1581 follow-up candidate `942a9ebb`.
- #1489 exposure check for #1788 (its CI runs on the PR merge commit, so a new `llm_*` node enters the registry-driven tests):
  `llm_glm/services.json` declares `classType ["llm"]` with `modelTotalTokens` ≥ 131072 for every profile, so it cannot lower the
  min-based LLM-class floor; none of `glm-4.5 … glm-5.2` appear in `ContextOptimizer.MODEL_LIMITS`, so
  `test_fallback_table_never_disagrees_with_catalog` is unaffected. No action needed.
- Non-author activity since the last sweep: none on #683/#1489/#1607/#1612 (latest non-author events unchanged:
  #683 CodeRabbit COMMENTED 14:27Z — triaged non-actionable; #1489 dsapandora CHANGES_REQUESTED 09-07; #1607/#1612 dismissed
  approvals 09-07). #1607/#1612 `mergeable` reads UNKNOWN while GitHub recomputes after the develop push — re-read in the final sweep.
- #1581 follow-up `942a9ebbcf53a4a97283434478eb4724c30430ae` (parent `8e7ef723`, unpushed; 8 files +410/−51; no `uv.lock` in the
  commit — the untracked one lives only in the engineer worktree). Lead read of `run_eval`, `reporters.py`, `__init__.py`,
  `main.py`, both docs hunks and the 14 new test names done; independent-verifier wave 3 running. Remote head re-confirmed
  `8e7ef723` before push. Final reply texts staged at `post/1581-thread-replies-final.md` (T2 completed / T3 written by the lead —
  the engineer's drafts were truncated in its report).
- Independent-verifier wave 3 on `942a9ebb`: ACCEPT on diff scope, semantics (exit paths byte-identical bar the swap; `--json` stdout
  pure; all-specs-errored → 2 with reports carrying the errors; `--fail-fast` unchanged), report shapes (JSON keys appended, JUnit
  totals consistent, single XML escaping incl. NUL/ESC stripping), tests (211 passed; revert → 6 failed + ImportError), ruff, `--help`.
  NEEDS-CHANGE on one doc: `packages/docs/content-static/cli.mdx` (eval section authored by this PR in `f7ca6367`) still carried the
  old `--json` shape and exit-1 wording. Fixed by the lead (table row, exit-code sentence, one-line note, one troubleshooting bullet)
  and folded into the same commit by amending the unpushed candidate → `be41c2e05b083daaaa2baf2238d21e418bc97b9a`
  (parent `8e7ef723`; 9 files +425/−55; code byte-identical to the verified `942a9ebb`). Reply drafts corrected per the fact-check:
  T2 names the three reverted files; T3 enumerates `cli.mdx`. `builder docs:build` not run locally (no node toolchain in the
  worktrees; the site build runs only on push to develop) — disclosed as a limitation, as for the other PRs.
- PUSHED 2026-09-10: `be41c2e05b083daaaa2baf2238d21e418bc97b9a` → `origin/feat/RR-1578-eval-runner` (fast-forward `8e7ef7230..be41c2e05`;
  remote re-confirmed `8e7ef723` immediately before; `git ls-remote` reads back `be41c2e0`). First attempt was a no-op: zsh treated
  `$NEW:refs/...` as a `:r` modifier and git rejected the mangled refspec before contacting the remote. CI watch started on the new head.
- CI on `be41c2e0`: run 34502903010 — `CI OK` success (15 passed / 4 expected skips at conclusion; 21/4 check-runs after the non-gating
  extras finished; nothing cancelled). CodeRabbit re-reviewed the push and, at 16:52–16:58Z, resolved its three threads itself, then
  replied to each of my replies with an explicit verification (T1 "documentation now matches the eval parser", T2 "verified … SpecError
  records … all report renderers", T3 "confirmed"). Zero unresolved threads on all five PRs.
- Published for the #1581 follow-up: replies r3981536094 / r3981536566 / r3981537093; summary comment 5621373826 edited in place
  (Follow-up paragraph); description sync section extended. No new summary comment, no re-review ping beyond the one already made.
- Correction published on #683: the summary comment 5621661633 and the description linked run 34492098463, which is the
  `pull_request_target` "PR checks" labeler run; the `CI OK` gate ran in CI workflow run 34492100993 (same head `3dc37c65`, success).
  Both texts patched in place (17:01Z); local reports corrected.
- FINAL SWEEP 17:00Z (develop tip `fd7d9565`, #2046 since `bb766ae3`): #683 `3dc37c65`, #1489 `90b8e247`, #1607 `b2d6d5bd`,
  #1581 `be41c2e0`, #1612 `1d16eed5` — all OPEN, MERGEABLE/BLOCKED (review gate only), `CI OK` green on every head, merge-tree CLEAN
  vs `fd7d9565`, 0 unresolved threads, no non-author activity since 12:00Z other than CodeRabbit (triaged: #683 re-review
  non-actionable; #1581 re-review = the three verified acknowledgements). Review decisions: #683/#1489 CHANGES_REQUESTED (standing
  human reviews, addressed); #1607/#1581/#1612 REVIEW_REQUIRED (pre-sync approvals dismissed by the new heads).
- 2026-09-11 03:24Z — second re-review ping on all five at the user's request (see published-replies.md). Formal reviewer re-request
  via REST succeeded for dsapandora on #683/#1607/#1581/#1612 (the 2026-09-10 attempt had returned 404). Develop tip `3626e659`;
  all five heads still CLEAN, `CI OK` green, no reviewer activity overnight.

## 2026-09-11 — Round 3: asclearuc's inline notes on the four approved PRs (user request: fix all, team, re-verify, push, re-tag)

- 08:06–08:12Z asclearuc APPROVED #1489 (`90b8e247`), #1581 (`be41c2e0`), #1607 (`b2d6d5bd`), #1612 (`1d16eed5`); each approval carries inline notes
  drafted 2026-09-10 (unresolved: #1612 ×2, #1607 ×3, #1581 ×2, #1489 ×3 = 10). #683: no new asclearuc review (Jul-29 CHANGES_REQUESTED stands).
- Known cost: pushing fixes will dismiss the fresh approvals (repo dismisses stale approvals on push, as seen with dsapandora on 09-10);
  the user asked for the fixes and a re-tag, so proceed and say so in each comment.
- Team: eng-1612 / eng-1607 / eng-1581 / eng-1489 (Opus, isolated worktrees, one commit each on the exact PR head, no push);
  review-triage-da (Fable) validates all ten claims + rechecks #683 + cross-PR collisions; verifier wave after commits; second pass after.
- Engineer commits (unpushed, parent = approved head): #1612 `cbd35889f94e55c072a1176447c4ddf3d005cf5a` (8 files +348/−38; otel test deps
  declared in `packages/server/build-requirements.txt` + `rocketride[otel]` in dev/test extras, hard imports; `build_providers(with_tracer,
  with_meter)`, `_chain_shutdown`); #1607 `bbffc010f32274e8f936cec812c6311fae417d93` (8 files +262/−24; `if:` covers pull_request_target,
  head-absent warning, README option 3 rewritten with a head checkout — SECURITY REVIEW PENDING; `_json_equal` version check; `_md_cell`
  backslash fix probed against cmark-gfm); #1581 `335d3ec0c` (9 files +305/−144; shared `--json [FILE]` via `Output`; `json_arg` removed;
  `expand_file_patterns` in file_utils; 241 tests). Verifiers launched: verify-1612, verify-1581, verify-1607. eng-1489 + review-triage-da running.
- Cross-PR: #1612 really uses `json_arg=False` for `otel` (main.py:255 at `1d16eed5`), so it keeps the helper hunk; with #1581 dropping it,
  only #1612 modifies `_add_connection_args` → the "byte-identical hunk / second land auto-merges" note in #1581's description is stale and
  must be replaced in this round's description update.
- verify-1581 (Fable): PUSH-READY, no corrections (helper parity with develop f9a25cbb proven; `Output` semantics proven; exit codes
  untouched; 241 tests + fails-before; ruff clean; drafts accurate). Residuals for the maintainer: unwritable `--json FILE` keeps the exit
  code (shared `Output` contract) while unwritable `--junit` exits 2; `nargs='?'` footgun `eval --json a.eval.json b.eval.json` (same as
  validate); validate/list docs understate `--json [FILE]` (pre-existing); `cli/utils/__init__.py` `__all__` omits the new helper (cosmetic).
- Lead second pass on `335d3ec0cc10f745c03bcb3c047698d8304d81e0`: 239 passed (six eval modules + validate + file_utils) in the verifier venv.
- PUSHED 2026-09-11: #1581 `be41c2e05..335d3ec0c` (remote re-confirmed `be41c2e0` first; read back `335d3ec0`; reviewDecision → REVIEW_REQUIRED,
  i.e. asclearuc's approval dismissed by the push as predicted). CI watch started.
- verify-1612 (Fable): PUSH-READY after a wording fix. CI mechanism confirmed line by line (`client-python:test` → `server:build` →
  `setup-test-deps` → `depends('build-requirements.txt')` installs into the same engine interpreter that runs pytest on all three OS legs;
  extras and `--pytest-preinstall` never reach CI; no lock-check reads `build-requirements.txt`; zero runtime image weight; wheels
  py3-none-any). 143 otel tests / 0 skipped with the extra; collection error exit 2 without it; fails-before 7/9. Residual: unpinned lines
  float if crewai/chromadb drop their OTel pins → LEAD added `>=1.27.0` floors (matching the `[otel]` extra and `mcp>=1.2.0` in the same
  file) and fixed the "synced source tree" phrase in the commit body; amended → `3a4c06aab927064754533319daa34af9e6106836`
  (parent `1d16eed5`; diff vs `cbd35889` = build-requirements.txt only). Lead second pass: fresh venv (opentelemetry 1.44.0), 143 passed.
- PUSHED 2026-09-11: #1612 `1d16eed5f..3a4c06aab` (remote re-confirmed `1d16eed5` first; read back `3a4c06aa`; reviewDecision → REVIEW_REQUIRED).
  CI watch started; the run log must show `test_otel_setup.py` collected and PASSED (0 skipped) — recipe in verify-1612's report
  (Build / Ubuntu 22.04 → Test step → `tests/test_otel_setup.py::test_build_providers_skips_the_*_half_when_not_requested PASSED`).
- verify-1607 (Fable): code/tests/YAML/lint ACCEPT; SECURITY NEEDS-CHANGE. `action.yml` L140 `python -m pip install` and L155 `python -c`
  run with the checkout as CWD (`sys.path[0]`), so PR-controlled `pip/` or `importlib/` packages in the checkout execute (reproduced on
  3.12/3.14); under `pull_request_target` with a PR-head checkout that is code execution with the persisted writable token. L155 is the
  DEFAULT path today (PyPI 1.3.0 has no `diff`, so the verify step fails). The engineer's README recipe reversed the parent's correct
  "never check out the PR head" guidance. LEAD DECISION: take asclearuc's second option — keep the `if:` fix + head-absent warning, drop the
  head-checkout recipe, steer fork PRs to `pull_request` + job summary and `workflow_run` for comments; add `python -I` to both invocations.
  Correction sent to eng-1607 (amend in place). #1607 NOT pushed yet. Reply drafts: T1 rewrite; T2 "two regression tests plus a control";
  T3 "emitted Markdown table". `cli.mdx` overlap with #1581: none (#1607 touches L546–551; #1581 L15/L141/L311–317).
- verify-1489 (Fable): code/tests/lint/config_int/lock ACCEPT; NEEDS-CHANGE on README:35 ("errs high" false under real tiktoken: the blanked
  rendering omits the line break after a non-empty role → overhead ≤2 tokens low; the engineer's repro still passes 1633 through 1632 with
  real cl100k) and on T1's stub-derived numbers. Recommended +2 margin. LEAD applied: `_ROLE_BREAK_MARGIN = 2` in `prompt_overhead_tokens`,
  README sentence corrected, test expectation 77→79; amended → `cd5db1b1c0f9263ef78825d881b529a974561c91` (parent `90b8e247`; diff vs
  `2b9cc4bf` = IInstance.py/README.md/test_all.py). Lead second pass: ruff clean; stub 194 passed/1 skipped; real tiktoken 0.14.0 195 passed.
  Residuals for the maintainer (from the verifier): per-entry markup over-count scales with entry count (~9 tokens per doc/history entry;
  ~1000 docs alone would empty an 8k window); the JSON-repair retry instruction (~30 tokens) is not measured; warn-once per pipeline run.
- PUSHED 2026-09-11: #1489 `90b8e247f..cd5db1b1c` (remote re-confirmed `90b8e247` first; read back `cd5db1b1`; reviewDecision stays
  CHANGES_REQUESTED — dsapandora's standing review, not affected by pushes). CI watch started.
- eng-1607b (Opus, correction pass, worked in the original engineer worktree): amended `bbffc010` → `05278aae1d4f1f4e63ae2879269fb202640a3013`
  (parent `b2d6d5bd`; 8 files +244/−26; diff vs `bbffc010` = README.md / action.yml / cli.mdx / pipe-diff-example.md only; engine.py,
  reporters.py, tests byte-identical). Option 3 now says NOT to check out the PR head under `pull_request_target` and routes fork comments via
  `pull_request` + `workflow_run`; `python -I -m pip install` and `python -I -c` (proof: hostile `pip/` in CWD hijacks `python -m pip`,
  `-I` resolves the real pip 26.2.1); warning/comment texts and the commit body corrected. Lead second pass: YAML 6 steps, 2 `if:` balanced,
  0 `${{` in run blocks, 104 tests, ruff clean, no residual head-checkout advice (README L75 is the `install-from` prohibition).
- PUSHED 2026-09-11: #1607 `b2d6d5bda..05278aae1` (remote re-confirmed `b2d6d5bd` first; read back `05278aae`; reviewDecision → REVIEW_REQUIRED).
  All four round-3 heads pushed: #1581 `335d3ec0`, #1612 `3a4c06aa`, #1489 `cd5db1b1`, #1607 `05278aae`. CI watches running on all four.
- #1489 CI on `cd5db1b1` FAILED (run 34600524213, all three Build legs, Test step): 1 of 4598 nodes tests —
  `test/test_dynamic.py::TestDynamicNodes::test_node_cases[context_optimizer:services:test2:ci_tiny]`, case_2 "compresses over-budget
  history": `history[1].content` index out of range. Reproduced locally (real tiktoken): the 80-token `ci_tiny` window loses 27 tokens to the
  measured markup (4 `role:` prefixes, 2 headers, CRLFs, +2 margin) → history budget 28 → 20 → only the first message survives; the
  summary placeholder needs ≥24. Cases 1/2 conflict at any single window with the original inputs (case 1's 81-token question only
  truncates below 88; case 2 needs ≥96). Fix: recalibrate the CI-only fixture — 112 tokens + 160-word question — evaluated over
  W∈{96…160} × words∈{80,120,160,200}: all three cases OK at 112 with margin (q→125 chars; hist budget 29; oversized doc excluded until 140).
  First attempt amended the pushed `cd5db1b1` (local `e7ff3a26`, abandoned): the ancestor check refused the non-fast-forward — correct;
  re-done as follow-up commit `30011d2f1b85eb971a9179ea532f21cfdfdc6edd` (services.json only) and PUSHED fast-forward
  (`cd5db1b1c..30011d2f1`; read back). Unit suites unchanged (194/1 stub, 195 real). CI watch restarted.
- #1489 CI on `30011d2f`: run 34602242917 `CI OK` success (17/4). Published 13:29–13:30Z: replies r3989594719 / r3989595207 / r3989595668,
  three threads resolved, comment 5635152830 (names both commits), summary 5620930259 + description updated. Round 3 complete: 10/10 items
  DONE across #1612 / #1607 / #1581 / #1489; each PR's asclearuc approval was dismissed by its push (branch protection) and a re-stamp
  requested once per PR; #1489 additionally still needs dsapandora's re-review. #683 untouched this round (nothing new to answer).

## 2026-09-11 — Round 4: dsapandora's approvals with one inline note each (#1612, #1489)

- 14:19Z dsapandora APPROVED #1612 (`3a4c06aa`) and #1489 (`30011d2f`); #1489's reviewDecision flipped to APPROVED (their 09-07 block lifted).
  Notes: #1612 root 3990053546 (`packages/server/build-requirements.txt:24`): the OTel deps now ride the engine's build harness for every engine
  build, and the summary's "zero new base dependencies" overstates it; alternative = install the `[otel]` deps only for the client-python test
  step (also removes the crewai coupling); "either way, soften the summary line". #1489 root 3990050591 (`requirements.txt:1`): the lock pins
  `tiktoken==0.13.0` so `<1.0.0` changes nothing today and may conflict when the lock moves to 1.x; bare `tiktoken` would track the lock;
  "not blocking" — conflicts with asclearuc's accepted round-3 ask for the `<1.0.0` house bound.
- No new CodeRabbit reviews on the round-3 heads; #1607/#1581 unchanged (asclearuc re-stamp pending).
- Plan: eng-1612-r4 (Opus) implements the client-python-scoped install + restores build-requirements.txt; da-round4 (Fable) validates both notes,
  decides #1489 (default: reply-only, keep asclearuc's bound, preserve the approval), drafts replies; verifier pass on the #1612 commit; push
  #1612 (approval will be dismissed again → re-request), CI log proof, replies, resolve, comment, description wording fix (two claims), summary.
- 14:34Z asclearuc RE-STAMPED all four round-3 heads (#1612 5179586678, #1489 5179586499, #1607 5179603737, #1581 5179591892) — with three new
  inline threads (#1607 ×2: false "No .pipe files changed" comment under pull_request_target; backslash-before-pipe; #1581 ×1: exit-2 paths
  bypass the `Output` envelope). All four `BLOCKED` despite APPROVED + green CI → consistent with require-conversation-resolution.
- da-round4 (Fable): #1612 note PARTIAL ("every engine install carries OTel" true for dev/CI builds, false for shipped tarball/Docker); the
  move is mechanically sound (depends() on a package-local file; precedent packages/ai/tests/requirements.txt); recommends wording-only to keep
  both approvals, push variant acceptable. #1489 note PARTIAL — "the lock wins regardless" is false at runtime (depends() never reads
  constraints.lock; compiles per-machine constraints), the bound duplicates chunker's (brake, not conflict), 10/124 node files carry upper
  bounds; recommends keep + reply. LEAD: #1489 reply-only (posted r3990338024, resolved → MERGEABLE/UNSTABLE, approvals intact);
  #1612 push the move (user asked to fix; strictly better engineering; both approvals will be dismissed → re-request both).
- eng-1612-r4 (Opus): `2bf3e65ef41feb7c9978838f420b1167968ededb` (parent 3a4c06aa; 6 files +64/−21): `client-python:setup-test-deps` action
  (tasks.js:209-227/289/307) → depends() on new `packages/client-python/tests/requirements.txt`; build-requirements.txt byte-identical to
  1d16eed5; docstrings + pyproject comment updated; `--list-deps` graph proven; depends() dry run proves constraints bind; 143/0; exit 2 w/o otel.
  verify-1612-r4 running. eng-1607-r4 and eng-1581-r4 launched for asclearuc's three new notes.
- #1489 after the reply-only resolution of dsapandora's note: `MERGEABLE / CLEAN / APPROVED` (dsapandora + asclearuc), 0 unresolved threads —
  the first of the five to reach READY TO MERGE. Confirms the conversation-resolution gate: the open thread, not the review states, was the block.
- verify-1612-r4 (Fable): PUSH-READY; wiring reproduced via `./builder --list-actions` / `client-python:test --list-deps` (no build needed);
  `depends()` reproduced with the real module (pin binds; bad pin → exit 1; missing file → silent skip, backstopped by the hard imports);
  side effects none (not globbed, wheel-excluded, check-externals/lock/Docker untouched); 143/0 + 213 offline; exit 2 without otel; ruff,
  node --check, prettier clean. Reply wording fixed per verifier ("byte-identical with develop and with 1d16eed5"; coupling sentence softened).
- PUSHED 2026-09-11: #1612 `3a4c06aab..2bf3e65ef` (remote re-confirmed `3a4c06aa`; read back `2bf3e65e`; reviewDecision → REVIEW_REQUIRED —
  dsapandora's and asclearuc's approvals dismissed as predicted). CI watch started.
- eng-1607-r4 and eng-1581-r4 STALLED (harness watchdog, no progress 600s). #1607 worktree kept coherent partial action.yml edits (+53/−2);
  #1581 worktree clean. Relaunched as eng-1607-r4b / eng-1581-r4b working in the same worktrees.
- eng-1581-r4b (Opus): `5dd841ea1` on r4/1581 (parent 335d3ec0; 6 files +131/−26): `out = Output(args.json)` before the spec loop; both exit-2
  paths → `out.fail(...)` + explicit `return 2`; manual stderr prints removed; `finally` (disconnect_all → finish) covers every return; 5 new
  tests (4 fail before); 221 eval + 25 others; ruff clean; envelope sentence in the three docs pages, docstring and `--help` description.
  Deviation: keeps the cause in the message because `hint_for` misses macOS's error texts (Linux's "Connection refused" does match — reply
  wording must not overclaim). Found `validate` has the same gap (out of scope; mention in reply). verify-1581-r4 launched.
- eng-1607-r4b (Opus): `b326f9c5fe6ad134098e2f6efd74e7ed34809515` on r4/1607 (parent 05278aae; 4 files +195/−13). Note 1: `head_missing`
  flag → `head-missing` step + action output; `> [!WARNING]` body/summary naming the unseen SHA + README pointer; comment step gated
  (`head-missing != 'true'`) so it can never overwrite a real diff; moved base labelled; 7-state shell harness, 16 intended diff lines vs the
  parent's block; YAML/bash-n/shellcheck/`${{` clean; README updated. The stalled engineer's partial edit had a column-0 quoted string that
  broke the YAML literal block — repaired. Note 2: NOT implemented with evidence — cmark-gfm longest-match cell scanning keeps `\|` escaped
  for any run of backslashes; current output `\d+\\|x` renders `\d+\|x`; asclearuc's one-liner would render an extra backslash and turn 8
  tests red incl. a pre-existing green one; docstring documents the rule; 2 tests added (exact bytes; cmark-gfm round-trip under skipIf).
  106 tests. verify-1607-r4 launched (independent rendering of the disagreement; skipIf question).
- #1612 CI on `2bf3e65e`: run 34615044697 `CI OK` success (17/4); log proof: `client-python:setup-test-deps` ran after "Build dependencies"
  and before `py-test-server:setup` on Ubuntu/macOS/Windows, otel mapper 46 / setup 29 collected + PASSED, 0 collection errors, only the
  gRPC-installed skipif (+ Windows signal-handler skip). Published 15:40Z: reply r3990822932, thread resolved, comment 5636914892,
  description L3/L107/L121 reworded + round-4 bullet, summary addendum; dsapandora + asclearuc re-requested. 0 unresolved threads.
- verify-1581-r4 (Fable): PUSH-READY, no code changes; reply wording fixed (hint_for misses asyncio's wording on macOS AND Linux; only
  Windows matches). Residuals: `--junit` stale on exit-2 paths (declared); `validate` has the identical stale `--json FILE` gap (Python
  validate.py:136, TS validate.ts:212) — separate PR; auth-rejection prefix slightly off but pre-existing.
- Lead second pass on `5dd841ea1eedaa65b6cabfd855ed13039dcc4c18`: 244 passed (six eval modules + validate + file_utils).
- PUSHED 2026-09-11: #1581 `335d3ec0c..5dd841ea1` (remote re-confirmed `335d3ec0` first; read back; reviewDecision → REVIEW_REQUIRED —
  asclearuc's 14:34Z approval dismissed by the push). CI watch started.
- verify-1607-r4 (Fable): PUSH-READY. Note 2 settled with GitHub's own /markdown API + cmarkgfm + comrak: no row splits for n≥1 backslashes
  before a pipe; today's `\d+\\|x` renders `\d+\|x`, asclearuc's form renders an extra backslash; cmark-gfm source (`table.c` unescape_pipes,
  re2c DFA longest match) matches the engineer's model. Note 1 harness reproduced over 7 states (only intended differences). One test-prose
  error (docstring: "an unescaped pipe adds a column" — GFM discards excess cells) + assertion restructure → LEAD applied, amended
  `b326f9c5` → `c16b0eb912d7f2809c05246b9e169a04b7e72623` (diff vs b326f9c5 = test file only, +5/−3); 106 tests; ruff; lefthook hooks passed.
  Reply R2 reworded per verifier (GitHub API sentence; "left `_md_cell` as it is"; skip disclosure). The cmark-gfm round-trip test skips in
  CI (cmarkgfm not installed) — disclosed in the reply; the exact-bytes test runs in CI.
- PUSHED 2026-09-11: #1607 `05278aae1..c16b0eb91` (remote re-confirmed `05278aae` first; read back; reviewDecision → REVIEW_REQUIRED —
  asclearuc's 14:34Z approval dismissed). CI watch started.
- #1581 CI on `5dd841ea`: run 34617839997 `CI OK` success (16/4). Published 16:09Z: reply r3991090709, thread resolved, comment 5637273338,
  description round-4 bullet, summary addendum; asclearuc re-requested. 0 unresolved threads; REVIEW_REQUIRED pending re-stamp.
- #1607 CI on `c16b0eb9`: run 34619198961 `CI OK` success (16/4). Published 16:28Z: replies r3991262387 (head-missing gate) and
  r3991262996 (backslash-before-pipe: evidence-backed disagreement), both threads resolved, comment 5637497919, description round-4 bullet,
  summary addendum; asclearuc re-requested. Round 4 complete: 15/15 items DONE across rounds 3–4.
