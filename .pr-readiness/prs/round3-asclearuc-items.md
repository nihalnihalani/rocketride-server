# Round 3 — asclearuc's inline notes (filed with APPROVE on 2026-09-11 08:06–08:12Z; drafted 2026-09-10)

Heads at start of round: #1612 `1d16eed5f0af20c4669b84f288b47bac51dbc322`, #1607 `b2d6d5bda711ddbde084fa8b85bfd619aa6671f2`,
#1581 `be41c2e05b083daaaa2baf2238d21e418bc97b9a`, #1489 `90b8e247f97e55b235e859f241b742c051bdb34e`, #683 `3dc37c65671c29c32e9f0b1f12d8288fc40fed8e` (no new review).
Develop tip at start: `3626e659` — all five heads merge CLEAN.

| # | PR | Thread (root) | File | Severity (reviewer) | Ask | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | #1612 | PRRT_kwDOROCxS86hMYwk (3982151058) | tests/test_otel_mapper.py:39 | should fix | otel test dependency is inherited via agent_crewai's transitive pin; make it declared/installed so 1 455 lines of tests cannot silently skip | eng-1612 | DONE — CI green (otel modules proven in the log), replied, resolved, commented |
| 2 | #1612 | PRRT_kwDOROCxS86hMYwp (3982151065) | otelbridge/bridge.py:186 | nit | caller-supplied `shutdown_fn` orphans providers + export thread; chain shutdowns; unneeded provider half built | eng-1612 | DONE — CI green (otel modules proven in the log), replied, resolved, commented |
| 3 | #1607 | PRRT_kwDOROCxS86hLqMA (3981860317) | .github/actions/pipe-diff/action.yml:429 | should fix | comment step `if:` excludes `pull_request_target`, contradicting README option 3 | eng-1607 | DONE — CI green, replied, resolved, commented |
| 4 | #1607 | PRRT_kwDOROCxS86hLqMX (3981860355) | pipediff/engine.py:319 | nit | version comparison uses `!=` instead of `_json_equal` (1→true / 0→false missed) | eng-1607 | DONE — CI green, replied, resolved, commented |
| 5 | #1607 | PRRT_kwDOROCxS86hLqMe (3981860363) | pipediff/reporters.py:593 | nit | `_md_cell` doubles backslashes inside code spans (`C:\Users` → `C:\\Users`) | eng-1607 | DONE — CI green, replied, resolved, commented |
| 6 | #1581 | PRRT_kwDOROCxS86hLmnS (3981838026) | cli/main.py:279 | should fix | `eval --json` is store_true; every other subcommand is `--json [FILE]`; `--json report.json` swallowed by `files` → exit 2 | eng-1581 | DONE — CI green, replied, resolved, commented |
| 7 | #1581 | PRRT_kwDOROCxS86hLmnY (3981838038) | cli/commands/eval.py:79 | should fix | `_expand_files` duplicates validate.py:49; move beside `find_files` in cli/utils/file_utils.py | eng-1581 | DONE — CI green, replied, resolved, commented |
| 8 | #1489 | PRRT_kwDOROCxS86hLhxR (3981807901) | context_optimizer/optimizer.py:946 | should fix | token count covers 4 fields; `Question.getPrompt()` also renders instructions/examples/context/goals + markup; count as overhead (option 2) or budget them (option 1) | eng-1489 | DONE — CI green on `30011d2f`, replied, resolved, commented |
| 9 | #1489 | PRRT_kwDOROCxS86hLhxY (3981807911) | context_optimizer/requirements.txt:1 | should fix | `tiktoken>=0.7.0,<1.0.0` (house norm from chunker) | eng-1489 | DONE — CI green on `30011d2f`, replied, resolved, commented |
| 10 | #1489 | PRRT_kwDOROCxS86hLhxq (3981807933) | context_optimizer/optimizer.py:183 | nit | use `ai.common.utils.config_int` for `max_context_tokens` | eng-1489 | DONE — CI green on `30011d2f`, replied, resolved, commented |

Approval bodies (verbatim key lines):
- #1612: "Two non-blocking notes inline. The first is worth acting on" (otel test dependency).
- #1607: "Three inline notes, none blocking. The first is the one worth acting on" (pull_request_target).
- #1581: "Two non-blocking notes are inline … Neither blocks the merge."
- #1489: "Three non-blocking notes are inline … None of them block the merge."

Consequence acknowledged: pushing fixes dismisses these approvals (repo dismisses stale approvals on push — dsapandora's on 2026-09-10). User instructed: fix all, push, re-tag asclearuc.

## Round 4 — dsapandora's inline notes (2026-09-11 14:19Z, filed with APPROVE)

| # | PR | Thread (root) | File | Ask | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | #1612 | 3990053546 | packages/server/build-requirements.txt:24 | OTel deps should be installed only for the client-python test step, not the engine harness; soften "zero new base dependencies" | eng-1612-r4 + da-round4 | DONE — `2bf3e65e` pushed, CI green + log proof, replied, resolved, commented, re-requested |
| 12 | #1489 | 3990050591 | context_optimizer/requirements.txt:1 | bare `tiktoken` would track the lock; `<1.0.0` may conflict later (not blocking; conflicts with asclearuc's accepted ask) | da-round4 (decision) | in progress |
| 13 | #1607 | 3989965331 (PRRT_kwDOROCxS86hgBt-) | .github/actions/pipe-diff/action.yml:333 | should fix: under pull_request_target with the head missing, the sticky comment says "No .pipe files changed" (false) and can overwrite a real diff; flag `head_missing`, honest body or skip the comment | eng-1607-r4b | DONE — CI green, replied, resolved, commented, re-requested |
| 14 | #1607 | 3989965346 (PRRT_kwDOROCxS86hgBuJ) | pipediff/reporters.py:607 | nit: backslash immediately before a pipe splits the row; double only backslashes that run into a pipe; the round-3 test pinned the wrong output | eng-1607-r4b | DONE — CI green, replied, resolved, commented, re-requested |
| 15 | #1581 | 3989955352 (PRRT_kwDOROCxS86hgADR) | cli/commands/eval.py:127 | should fix: both `return 2` paths bypass `Output`, so `--json FILE` writes nothing (stale-file hazard); `out.fail(...)` + `return 2`, `out` created before spec loading | eng-1581-r4b | DONE — CI green, replied, resolved, commented, re-requested |

Round-4 status: item 12 (#1489) DONE — reply r3990338024 posted (keeps asclearuc's bound; reasoning), thread resolved, #1489 now MERGEABLE/UNSTABLE with two approvals (dsapandora 14:19Z, asclearuc 14:34Z). Item 11 (#1612) — commit `2bf3e65e` under verification.
