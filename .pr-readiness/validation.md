# Validation record (lead-owned PRs; CLI trio appended from validation-cli.md)
Environment: macOS arm64; python 3.12.12 venv (scratchpad/venv-cobalt); ruff 0.16.5 (CI develop pin); pytest 9.x; engine binary NOT built locally — every engine-hosted check is marked unavailable, never passed. Node suites run under a disclosed review-only shim (`sitecustomize.py`: `engLib`=MagicMock, `depends`=no-op, real `rocketlib`/`ai`/`rocketride` from source) mirroring nodes/test/tool_git/test_tools.py.

## #683 (feat/cobalt-pipeline-evaluation-consolidated)
| command | checkout | head | target | exit | result |
|---|---|---|---|---|---|
| `git merge upstream/develop` | lead worktree | d8ff8f9e→e1f06b4f | f9a25cbb | 0 after resolution | 1 conflict (docs/develop/README.md) resolved; see conflict-resolutions.md |
| `pytest -q nodes/test/cobalt` | same | 56072ad9 (amended: order-independent assertion + eval_cobalt README contract line, per verifier wave 1) | f9a25cbb | 0 | **230 passed, 1 skipped** (OPENAI_API_KEY); reversed-order subset 185 passed |
| `pytest -q nodes/test/cobalt -k "empty_text_clears or score_answer or evaluators_shim"` (post-fix) | same | 64571f50 | — | 0 | 6 passed |
| same, with the 3 source files reverted to e1f06b4f (fails-before) | same | e1f06b4f sources | — | 1 | **4 failed, 2 passed** (the 2 passing are the trivially-true negatives) |
| `ruff check` + `ruff format --check` (dataset_cobalt, eval_cobalt, nodes/test/cobalt) | same | 64571f50 | — | 0 | clean (30 files) |
Unavailable: `./builder test` (engine), `builder docs:build`, real-engine scoring run of examples/cobalt-evaluation.pipe (needs engine build + model credential) — reproducible command recorded in prs/683-changes.md; llm_judge integration test skipped (OPENAI_API_KEY).

## #1489 (feature/context-optimizer-node)
| command | checkout | head | target | exit | result |
|---|---|---|---|---|---|
| `git merge upstream/develop` | lead-1489 worktree | a61e8483→9b4cfcce | f9a25cbb | 0 | clean |
| `pytest -q nodes/test/context_optimizer/test_all.py` (shim; fixtures serve the REAL `{"services":…,"version":…}` envelope) | same | 12d8dc8c (amended after verifier wave 1: envelope unwrap + LLM-class floor) | f9a25cbb | 0 | **171 passed, 1 skipped** (real-tiktoken-only) |
| `ruff check` + `ruff format --check` (context_optimizer src+tests) | same | 12d8dc8c | — | 0 | clean |
| probe_1489.py — OLD optimizer.py (9b4cfcce) with no sibling llm_* dirs | same | 9b4cfcce src | — | 0 | catalog_ids=0, unknown-model budget **128000** > smallest known 8191 → UNSAFE (the review's defect reproduced) |
| probe_1489.py — NEW optimizer.py (12d8dc8c), registry stub serving the source tree in the real envelope shape | same | 12d8dc8c | — | 0 | catalog_ids=455 (envelope unwrapped), unknown-model budget **8191** = smallest chat-LLM-class window (embedding/vision 2048 deliberately excluded) → SAFE |
Note: the rewritten suite cannot run against the old module (it imports the new constant), so the before/after proof is the shared-surface probe above, not the suite.
Unavailable: engine-hosted run (real `rocketlib.getServiceDefinitions`), `nodes:docs-generate` (generated README block untouched), dynamic services.json cases.

## Target-branch movement during the task
- develop advanced f9a25cbb → 038ae3dd (one commit: "fix: prevent crashes and hangs in audio_player node (#1355) (#1365)", 5 files, none overlapping any authored PR). Freshness sweep at that point: no remote-head drift on #683/#1489/#1581/#1607/#1612, zero new comments/reviews since the start timestamp.
- Both lead candidates (64571f50, 8f820ae9) `merge-tree` clean against 038ae3dd. Tested context remains f9a25cbb; residual risk: none identified (disjoint files). CI on push will run against the live merge context.
- develop advanced again 038ae3dd → 617f2f44 ("fix(ai,ui): stop silently dropping webhook bodies sent on an unread lane (#2230)", 10 files, no overlap with any authored PR). All five candidates (#683 56072ad9, #1489 12d8dc8c, #1607 b2d6d5bd, #1581 8e7ef723, #1612 1d16eed5) `merge-tree` clean against 617f2f44. GitHub's CONFLICTING state on all five reflects the pre-sync remote heads (nothing pushed yet).
- #1581 head 8e7ef723: `Auto-label` (labeler workflow, not part of the CI OK gate) concluded CANCELLED (run 34488930751, 14:25–14:27Z) while every other head's Auto-label succeeded — classified environmental (workflow cancellation); rerun requires repository admin rights (`gh run rerun` → "Must have admin rights"), so it stays cancelled — non-gating, noted in the PR summary.

## #683 first CI run on 56072ad9 (run 34487052426) — FAILED, diagnosed and fixed
- Build / Ubuntu 22.04 and Build / Windows Server 2022: step `Test` failed; the ONLY failing test on both legs: `test/test_icons.py::test_every_user_facing_service_declares_an_icon` — `dataset_cobalt/services.json` and `eval_cobalt/services.json` declare no icon. Classification: integration failure introduced by the develop merge (develop's icon-manifest gate from #1815 landed after this PR's previous sync); not a cobalt-code regression, not a flake (deterministic on both OSes). develop's own contemporaneous red run (34484037624 @617f2f44) was an unrelated vcpkg/CMake download SSL failure at the Build step; develop's next run (ec44e5bb) has Ubuntu/Windows green.
- Fix 3dc37c65: co-located `dataset-cobalt.svg` / `eval-cobalt.svg` (24px, currentColor, viewBox) + `"icon"` declarations after `title` in both services.json. Local: `pytest nodes/test/test_icons.py` → 3 passed (develop's exact gate); `pytest nodes/test/cobalt` → 230 passed / 1 skipped; both services.json parse (json5). Pushed as a normal descendant of 56072ad9.
