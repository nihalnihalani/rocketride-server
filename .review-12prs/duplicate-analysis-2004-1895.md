# Duplicate analysis — PR #2004 vs PR #1895 (`send_files()` concurrency bound)

Owner: python-sdk-reviewer · Written after reviewing each PR independently (`prs/2004.md`, `prs/1895.md`).
Heads compared: **#2004 `0078e6413767c88648d8e7f388b8bbf3825cbe37`** · **#1895 `a75c20ef817b8333f1ae30ab7c28c2a81fc888f7`**
Baseline: develop `973cd9b45ead293dd22fb8f7036ef1a1b325ca6b`. Both heads re-verified unchanged at the end of the review.

Both PRs say **"Fixes #1841"**. They are genuine duplicates — same bug, same public API addition, same
default, six of nine files in common. Only one can merge.

---

## 0. Recommendation up front

**Keep #1895. Close #2004 after transferring four items.**

Neither is a strict superset. #2004 is a superset of #1895's *SDK semantics* (all ten of #1895's
concurrency tests pass against it) and fixes three real pre-existing bugs #1895 leaves alone. #1895 is
ahead on everything else that matters for merging: it is one commit behind develop with **green CI**,
it has no defects of its own, it fixes the `getsize` race at source instead of catching it, it does not
have #2004's result-overwrite bug, its doc cleanup is more complete, its CLI validation is more
idiomatic, and — decisively — it is the branch a maintainer has already reviewed in depth, whose nine
review items are all addressed, and which was explicitly asked to use the semaphore shape that #2004
does not use.

The four items to transfer are one-line each and listed in §8.

Newer is not better here: #2004 was opened eight days *after* the review that shaped #1895 into its
current form, and re-arrives at the shape that review moved away from.

---

## 1. Side-by-side: public semantics

| | **#2004** | **#1895** | verdict |
|---|---|---|---|
| Signature | `send_files(files, token, max_concurrent: int = 5)` | identical | tie |
| Return annotation | `-> List[UPLOAD_RESULT]` (**fixes a real pre-existing lie**) | `-> UPLOAD_RESULT` (unchanged; deferred by agreement) | **#2004** |
| Validation of the limit | `bool`, non-`int`, `< 1` → `ValueError`, before *anything* | identical rule | tie |
| Where validation sits | before the empty-list check | after the empty-list/token checks | tie (both before any I/O) |
| `0 / -1 / True / 5.0 / '5' / None` | all `ValueError` (measured) | all `ValueError` (measured) | tie |
| Empty file list | `ValueError: Files list cannot be empty` | identical | tie |
| Result ordering | preserved (pre-sized list, index assign) | preserved (same) | tie — *already true on develop*, so this is a non-regression, not a feature |
| Per-file failure | `action: 'error'` entry, batch continues | identical | tie |
| `None` holes in results | impossible (worker guard fills every slot) | impossible in practice (the only known raise source removed) | tie |
| `Raises:` docstring accuracy | `FileNotFoundError` removed (never raised) | still lists `FileNotFoundError` | **#2004** |
| Scope of the bound | per invocation | per invocation | tie — neither documents it; two concurrent calls give 2×limit (measured) |

## 2. Side-by-side: algorithm + resource bounds (measured)

All figures from `<scratchpad>/harness_send_files.py`, driving the **real** `DataMixin.send_files` on
the **real** asyncio scheduler. Only the transport pipe (recording double, `open()` awaits 5 ms) and
`builtins.open` (counting wrapper) are substituted — `asyncio.gather`, the semaphore/pool and the loop
are untouched. Counters are peak-in-flight, not elapsed time. Python 3.12.12.

| measurement | develop | **#2004** | **#1895** |
|---|---|---|---|
| n=40, limit 5 — peak pipes | 40 | **5** | **5** |
| n=40, limit 5 — peak open fds | 40 | **5** | **5** |
| n=40, limit 5 — peak asyncio tasks | 41 | **6** | 41 |
| n=120, limit 5 — peak pipes / fds | 120 / 120 | **5 / 5** | **5 / 5** |
| n=120, limit 5 — peak asyncio tasks | 121 | **6** | 121 |
| n=8, limit 1 — peak pipes | 8 | **1** | **1** |
| limit 50 over 3 files — pipes / tasks | 3 / 4 | 3 / 4 | 3 / 4 |
| two concurrent calls, limit 5 each | 20 + 20 | 5 + 5 | 5 + 5 |

**Mechanism.** #2004: a fixed pool of `min(max_concurrent, len(files))` workers pulling from a shared
`next_index` cursor (`data.py:735-782`); read-and-increment with no `await` between, which is why it is
safe on one event loop. #1895: `asyncio.Semaphore(max_concurrent)` wrapping the existing
`upload_file()` call, `gather` shape unchanged (`data.py:738-750`).

**Where they differ that matters.** Both bound the two resources the issue is about — concurrent pipes
and, critically, concurrent **open OS file handles** (`upload_file` holds a handle across every
`await pipe.write(chunk)`, `data.py:652`, which is what made develop drop the caller's own files past
`ulimit -n`). Only #2004 additionally bounds *pending work*: task count stays at `limit + 1` instead of
`n + 1`. That is a real advantage at 10⁵–10⁶ files. It is a modest one, though: `normalized_files` and
`results` are O(n) in both, and normalisation stats every file before any upload begins, so the batch
is already O(n) in memory either way. Neither PR streams the input.

**Eager work up front:** identical in both — every file is normalised and `os.path.isfile`-checked
before the first pipe opens (develop behaviour, unchanged). Files are opened only inside `upload_file`,
i.e. after a slot is held, in both.

## 3. Side-by-side: failure, cancellation, cleanup

| | develop | **#2004** | **#1895** |
|---|---|---|---|
| One file's write fails (n=12, limit 4) | `errors_at=[3]`, batch completes | same, peak 4 | same, peak 4 |
| Pipes opened / closed on that batch | 12 / 11 | 12 / 11 | 12 / 11 |
| Failed pipe finalised? | no | no (undocumented) | no (**documented**, `data.py:698-703`) |
| File vanishes between `exists()` and `getsize()` | **`None` hole at `results[2]`** | `error` entry (upload had *completed*) | **`complete` entry, real byte count** |
| Tail of `upload_file` raises after the result was recorded | `complete` preserved | **`error`, `bytes_sent: 0` — overwrites a success** | `complete` preserved |
| Outer `task.cancel()` mid-flight | `CancelledError` propagates; 60 pipes stranded | propagates; 4 stranded | propagates; 4 stranded |
| Worker cancelled from *inside* (e.g. a nested `wait_for`) | n/a | re-raised, no holes (`data.py:772-780`) | would be captured by `gather` → hole |
| Shared-state interference between concurrent calls | n/a | none (pool + cursor are call-local) | none (semaphore is call-local) |

Three notes on this table.

* **The `close()` question is settled and both agree.** `DataPipe.close()` is the *finalize* call — it
  flushes and commits, and there is no abort subcommand — so closing a half-sent file would ingest a
  truncated document. #1895 tried adding a cleanup `close()` (`5e619598`), was blocked on exactly this
  ground, and reverted it (`39bb5a41`) with the reasoning written into the code. #2004 never added one.
  Same behaviour; #1895 leaves the explanation behind, which is worth keeping.
* **#1895 removes the `getsize` race; #2004 catches it.** #1895 captures `file_size` once inside the
  `try` (`data.py:637`, reused at `:712`). #2004 keeps develop's re-stat (`data.py:710`) and relies on
  the worker guard to turn the resulting `FileNotFoundError` into an `error` entry. But the upload had
  already *completed* — bytes written, `close()` returned — so #2004 reports a success as a failure. A
  caller retrying anything marked `error` re-uploads and duplicates. #1895's outcome is correct.
* **#2004 has a defect #1895 does not.** Its worker's recovery handler (`data.py:753-764`) writes an
  `error` entry **unconditionally**, but `upload_file` sets `results[index]` at `:723` and *then* calls
  `debug_message()` at `:729`, which invokes the caller's `on_debug_message` unguarded
  (`mixins/events.py:111-112`). Measured with a raising callback:
  `develop / #1895 → ['complete']*4, bytes_sent=[64,64,64,64]`; **`#2004 → ['error']*4,
  bytes_sent=[0,0,0,0]`**. One-line fix (`if results[index] is None:`), but it is currently there.

## 4. Side-by-side: tests

| | **#2004** | **#1895** |
|---|---|---|
| Count | 31 (one file) | 16 (10 concurrency + 6 CLI parser) |
| Bound assertions | peak-active counter; `test_bounded_does_not_grow_with_the_file_list`; a `gather_spy` counting the coroutines handed to `gather` | peak-active counter via a recording fake pipe |
| Ordering / one-result-per-file | `test_results_keep_input_order`, `test_every_file_is_uploaded_exactly_once`, `test_no_result_slot_is_left_empty` | ordering asserted inside the bound tests |
| Failure paths | `test_one_failure_does_not_strand_the_queue`, `test_no_worker_exits_by_exception`, `test_a_file_that_vanishes_mid_upload…` | `test_failed_file_does_not_stop_batch`, `test_failed_write_does_not_finalize_its_pipe`, `test_file_lost_mid_batch_still_gets_a_result` |
| Cancellation | `test_a_cancelled_worker_propagates…`, `test_cancelling_the_caller_still_propagates` | none |
| Contract/annotation | `test_signature_matches_the_typescript_client`, `test_docstring_no_longer_promises_unbounded_parallelism`, `test_returns_one_result_per_file_in_the_annotation_too` | none |
| CLI parser | none (CLI validated only through `_validate_args`, untested) | `test_defaults_match_typescript_cli`, `test_flags_are_independent`, `test_rejects_invalid_max_concurrent[0,-1,2.5,five]` |
| Methodology stated in the PR | mutation testing (9 mutants; 3 survived the first pass and each exposed a real defect the author then fixed) | mutation testing (3 targeted mutants) + a throwaway randomised harness (40 cases, 1-40 files, limits 1-12, 25 % injected failures) |
| CI at head | **Ruff FAILURE → CI OK FAILURE** | **20 green / 0 failing** |

**Cross-run (executed locally, both directions):**

```
#1895's tests against #2004's code   -> 12 passed, 4 failed  (all 4 in the CLI-parser file;
                                        all 10 concurrency tests PASS)
#2004's tests against #1895's code   -> 27 passed, 4 failed
```

The four failures each way, classified:

*#1895's tests failing on #2004* — all four are `test_rejects_invalid_max_concurrent[0 / -1 / 2.5 / five]`.
`0` and `-1` do not raise `SystemExit` at parse time under #2004 (`type=int` accepts them; the check
lives later, in `_validate_args`), and `2.5`/`five` produce argparse's generic
`invalid int value: '2.5'` instead of `must be a positive integer`. **Behavioural difference, not a
#2004 defect** — the user still gets a clear error before a pipeline starts. #1895's `positive_int`
converter is more idiomatic (one message, exit 2, and it works for any caller of `parse_args()`).

*#2004's tests failing on #1895* —

| test | real defect in #1895? |
|---|---|
| `test_returns_one_result_per_file_in_the_annotation_too` | **Yes** — `-> UPLOAD_RESULT` is wrong (§1) |
| `test_a_missing_file_raises_what_the_docstring_says` | **Yes** — `FileNotFoundError` still in `Raises:` |
| `test_a_file_that_vanishes_mid_upload_does_not_strand_the_queue` | **No** — it asserts `results[1]['action'] == 'error'`, i.e. #2004's *mitigation*. #1895 returns `complete` because it removed the race; that is the better outcome |
| `test_a_cancelled_worker_propagates_rather_than_returning_holes` | **No** — asserts `len(workers) == 3`, a structural property of the worker pool |

So of #2004's four extra failures, **two are real** and two are implementation-shaped tests. This is
the single most load-bearing classification in this document: reading all four as defects would flip
the recommendation.

## 5. Side-by-side: compatibility + scope

| | **#2004** | **#1895** |
|---|---|---|
| Backwards compatible signature | yes | yes |
| Behaviour change (unbounded → 5) | yes, acknowledged | yes, acknowledged and called out under "Breaking changes documented" |
| `packages/ai` `EngineClient` protocol (`mcp/engine.py:45`) | still satisfied | still satisfied |
| `types/data.py` `upload_time` semantics | changed silently (measured from slot acquisition, excludes queue wait) | **changed and documented** (`types/data.py:169`) |
| Files touched | 7 | 9 (adds `types/data.py`, `tests/test_cli_upload_args.py`) |
| Docs: three reference tables | yes | yes |
| Docs: `send_files` signature section (`ROCKETRIDE_python_API.md:530-541`) | no | **yes** |
| Docs: "all files uploaded concurrently" example line (`:336`) | no | **yes** |
| Docs: **Performance Considerations** (`:1113-1114`, *"server handles queuing and rate limiting automatically"*) | **no — still false** | **yes** |
| Docs: `--pipeline` → `--pipeline_path` (`:159`) | **yes** | no — still wrong |
| Docs: `--threads` explained as pipeline threads | yes (longer) | yes (shorter) |

The Performance-Considerations gap matters more than it looks: `docs/agents/ROCKETRIDE_python_API.md`
is the file agents are pointed at before writing RocketRide code, and joshuadarron called it out
by name on #1895 (item 4) precisely because an agent reading it *"omits `max_concurrent` and the user
reports the ingest as hung"*. #2004 leaves those two lines saying the opposite of what it just shipped.

## 6. Integration effort

| | **#2004** | **#1895** |
|---|---|---|
| Commits ahead of merge-base | 4 | 7 |
| Behind develop | 61 | **1** |
| merge-tree vs develop | clean | clean |
| Rebase needed | no | no |
| CI at head | red (`Ruff`) | green |
| Blocking defects of its own | 2 (`ruff format`; the result-overwrite) | 0 |
| Standing review to clear | none (only CodeRabbit) | **CHANGES_REQUESTED (joshuadarron)** — all nine items addressed; needs a re-review to dismiss |
| Work to merge | fix 3 items (§9 of `prs/2004.md`), then a first human review of a 591-line diff | transfer 3 one-liners, then ask for a re-review |

## 7. Unique content in each

**Only in #2004:**

1. `-> List[UPLOAD_RESULT]` return-annotation fix (`data.py:490`).
2. `FileNotFoundError` removed from the `Raises:` docstring (`data.py:509-511`).
3. `--pipeline` → `--pipeline_path` in `docs/agents/ROCKETRIDE_python_API.md:159`.
4. Bounded task count (worker pool) — `limit + 1` tasks instead of `n + 1`.
5. Re-raise of a `BaseException` outcome from `gather` so an internally-cancelled worker cannot leave
   holes (`data.py:772-780`).
6. Defensive `getattr(self.args, 'max_concurrent', 5)` in `UploadCommand`.
7. Cancellation and contract/annotation tests.
8. The observation (not a fix) that `ROCKETRIDE_typescript_API.md:179` claims a TS default of 64 while
   `client-typescript/src/client/client.ts:1766` says 5.

**Only in #1895:**

1. `file_size` captured once inside the `try` — removes the `exists()`→`getsize()` race at source
   (`data.py:637`, `:712`).
2. The written rationale for not finalising an interrupted pipe (`data.py:698-703`).
3. `types/data.py:169` — `upload_time` documented as excluding queue wait.
4. `ROCKETRIDE_python_API.md` **Performance Considerations** corrected (`:1113-1114`).
5. `ROCKETRIDE_python_API.md` `send_files` signature section (`:530-541`) and the `:336` example line.
6. `positive_int` argparse converter — parse-time rejection of `0/-1/2.5/five`, one message, exit 2.
7. `tests/test_cli_upload_args.py` — 6 parser tests.
8. Compliance with the maintainer's stated preference for `asyncio.Semaphore`.

## 8. If #1895 is kept — exactly what must transfer from #2004 before closing it

All three are one-line edits; none touches the concurrency mechanism.

1. **`packages/client-python/src/rocketride/mixins/data.py:491`** —
   `-> UPLOAD_RESULT` → `-> List[UPLOAD_RESULT]`. (`List` is already imported at `data.py:59`.)
   Regression test: `inspect.signature(DataMixin.send_files).return_annotation == List[UPLOAD_RESULT]`.
2. **`packages/client-python/src/rocketride/mixins/data.py:512`** — delete
   `FileNotFoundError: If any specified file doesn't exist` from `Raises:` (the code raises
   `ValueError` at `:596`). Regression test: the docstring's `Raises:` block does not mention
   `FileNotFoundError`.
3. **`docs/agents/ROCKETRIDE_python_API.md:159`** — `--pipeline` → `--pipeline_path`
   (the real flag, `cli/main.py:402`).

Worth considering but **not** required to close #2004 — carry these only if the maintainers want them:

4. A docstring sentence saying the bound is **per invocation** (`data.py:508-510`); measured, and
   missing from both PRs.
5. Cancellation tests (#2004 has two; #1895 has none). Behaviour is already correct in #1895
   (measured), so this is coverage, not a fix.
6. The bounded task count. This is #2004's one genuine architectural advantage and it does **not**
   transfer as a one-liner — it *is* the worker pool, which is the shape the maintainer asked #1895 to
   move away from. Recommend filing it as a separate issue ("bound pending work, not just in-flight
   work, for very large batches") rather than reopening the mechanism debate now.

## 9. If #2004 were kept instead — what must transfer from #1895

Recorded for completeness; not the recommendation.

1. `file_size` captured once inside the `try` (`data.py:637/712`) — removes the race instead of
   reporting a completed upload as `error`.
2. `if results[index] is None:` guard on the worker's recovery write (`data.py:753-764`) — otherwise a
   raising user `on_debug_message` turns successes into failures (measured).
3. `ruff format` on `mixins/data.py` and `tests/test_send_files_concurrency.py` — CI is red.
4. `ROCKETRIDE_python_API.md:1113-1114` Performance Considerations, `:530-541` signature section, and
   `:336` — still false after #2004.
5. `types/data.py:169` `upload_time` semantics.
6. `positive_int` for `--max-concurrent`, plus `tests/test_cli_upload_args.py`.
7. The rationale comment for not finalising interrupted pipes.

That is seven items including two defect fixes and a red CI, versus three one-liners the other way —
which is the arithmetic behind the recommendation.

## 10. Recommendation, restated with the reasoning

**Keep #1895; close #2004 with items 1-3 of §8 transferred.**

* #1895 has **no defects of its own**; #2004 has two (red `ruff format`, and a worker guard that can
  overwrite a successful result with a fabricated failure).
* #1895 handles the `getsize` race **better** — a completed upload is reported as completed, where
  #2004 reports it as an error and invites a duplicating retry.
* #1895 is **1 commit behind develop with green CI**; #2004 is 61 behind with red CI and has never had
  a human review.
* A maintainer has already reviewed this exact issue in depth on #1895, all nine items are addressed,
  and item 8 explicitly asked for the `asyncio.Semaphore` shape #1895 now has and #2004 does not.
  Merging #2004 would re-adopt the shape that review moved away from, without acknowledging it.
* #1895's documentation cleanup is more complete, including the agent-facing Performance
  Considerations section that #2004 leaves stating the opposite of what it ships.
* #2004's advantages are real but small and separable: three one-line fixes, plus one architectural
  idea (bounded pending work) that belongs in its own issue.

**Process note for the lead:** #1895's merge is blocked by a stale `CHANGES_REQUESTED` decision, not by
code. The action is to ask @joshuadarron to re-review, with the item-by-item reconciliation table in
`prs/1895.md` §4 as the starting point.

**Fairness note:** #2004's author disclosed being an autonomous AI agent and asked to be told if that
is unwelcome. That disclosure did not enter this comparison — the recommendation rests entirely on the
measured behaviour, the defect counts, the CI state, and the existing review record. #2004 is careful,
well-tested work that found three real pre-existing bugs, and it should be credited for them in
whatever lands.

---

## Draft GitHub comment for #2004 *(draft only — NOT posted)*

> Flagging an overlap: this and #1895 both fix #1841, and they touch six of the same files. Only one
> can land.
>
> I reviewed both independently and measured them side by side through the real scheduler. Both bound
> the thing that matters — peak pipes **and** peak open fds track `max_concurrent` exactly, independent
> of list length. Your worker pool additionally bounds task count (`limit+1` vs `n+1`), which is a real
> advantage at very large batches, and you fixed three genuine pre-existing bugs #1895 leaves alone:
> the `-> UPLOAD_RESULT` annotation, the `FileNotFoundError` that is never raised, and `--pipeline`
> → `--pipeline_path` in the agent doc.
>
> On balance my read is that #1895 should be the one to land, for reasons that are mostly not about
> the code quality of either:
>
> * #1895 is 1 commit behind develop with green CI; this branch is 61 behind and `Ruff` is red on two
>   of its own files (`mixins/data.py:769-771`, `tests/test_send_files_concurrency.py:388-390`).
> * #1895 removes the `getsize` race at source rather than catching it. Measured on the
>   "file deleted mid-batch" case: #1895 returns `complete` with the real byte count (the upload
>   *did* complete); this branch returns `error`, which invites a duplicating retry.
> * `data.py:753-764` writes the error entry unconditionally, but `upload_file` records the result at
>   `:723` and *then* calls `debug_message()` at `:729`, which invokes the caller's `on_debug_message`
>   unguarded. With a raising callback: `develop/#1895 → ['complete']*4, bytes_sent=[64,64,64,64]`;
>   this branch → `['error']*4, bytes_sent=[0,0,0,0]`. `if results[index] is None:` fixes it.
> * #1895 carries a CHANGES_REQUESTED review from @joshuadarron on this exact issue. Item 8 asked for
>   `asyncio.Semaphore` over a hand-rolled pool — non-blocking, and he agreed the pool is correct, but
>   it is a stated preference that this branch does not address. (Your branch does keep
>   `return_exceptions=True`, which was item 3's blocking objection there.)
> * `ROCKETRIDE_python_API.md:1113-1114` still says *"all files uploaded concurrently"* and *"the
>   server handles queuing and rate limiting automatically"* — the opposite of what this PR ships.
>   That is the file agents read before generating RocketRide code; #1895 fixes it.
>
> Cross-running the suites: your 31 tests against #1895 give 27 passed / 4 failed, and only two of
> those four are real defects there (the annotation and the `FileNotFoundError` docstring). #1895's ten
> concurrency tests all pass against your implementation.
>
> If the maintainers agree, the concrete ask is to lift three one-liners from here into #1895 — the
> annotation fix, the `Raises:` fix, and `--pipeline_path` — and to file "bound pending work, not just
> in-flight work" as its own issue, since that idea is worth keeping and does not survive as a
> one-liner. Your mutation-testing writeup is the most useful thing in either PR's description and is
> worth preserving in whatever lands.
>
> Deferring to maintainers on the final call.
>
> *(Review assisted by AI tooling; every number above was measured against `0078e641` and `a75c20ef`.)*

## Coordination notes

**@independent-verifier** — three things to re-derive before trusting the recommendation:

1. The cross-run classification in §4. Of #2004's four failures against #1895, exactly two are real
   defects; treating all four as defects inverts the conclusion. The two false ones assert #2004's own
   mitigation (`action == 'error'` for a file that actually uploaded) and its worker-pool structure
   (`len(workers) == 3`).
2. The result-overwrite (§3, third bullet). `<scratchpad>/probe_tail_raise.py`. The trigger must match
   only `upload_file`'s per-file `"…bytes, Xs"` line — matching `send_files`' summary line as well
   makes all three trees raise and looks like a false positive.
3. The `ruff format` attribution for #2004: whole-repo `ruff format --check` gives *"2 files would be
   reformatted, 1534 files already formatted"*, and both are files the PR changed — so it is not
   staleness.

On cancellation: my first probe reported "CancelledError swallowed" on all three trees and was
**wrong** (the batch had finished before `cancel()` landed). Assert `task.done() is False` at cancel
time. Corrected result: all three propagate.

**@typescript-sdk-reviewer** — whichever lands, the Python semantics for #1382 parity are the same:
default 5, bound is **per invocation** (two concurrent calls → 2×limit, measured), `bool`/float/str
limits rejected with `ValueError` before anything opens, results in input order, per-file failures as
`action: 'error'` entries, failed pipes deliberately left unfinalised for the server's zombie reaper.
Both PRs flag stale TypeScript docs they did not fix: `ROCKETRIDE_typescript_API.md:179` says the TS
default is 64 while `client-typescript/src/client/client.ts:1766` says 5, and
`ROCKETRIDE_typescript_API.md:347,1084-1085` plus
`packages/client-typescript/docs/guide/methods/send.md` still describe uploads as unbounded (stale
since #1716).

**@lead** — the decision needs a maintainer for one thing only: whether joshuadarron considers #1895's
nine review items resolved. Everything else in this analysis is measured. If he re-reviews and
approves, #1895 merges with three one-line additions; #2004 closes with credit for the three bugs it
found.
