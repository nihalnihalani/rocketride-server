# Wave-2 independent verification — CLI candidates #1607 / #1581 / #1612

Author: **independent-verifier** (wave 2). Read-only toward GitHub. **Nothing pushed, nothing
posted, no candidate modified.** All evidence reproduced from scratch in an isolated worktree
(`agent-ae43c33b63a0e0379`) plus `git archive` exports under this session's scratchpad; the
engineer's numbers were re-derived, not copied.

> Location note: the Write tool refuses paths outside this agent's worktree, so the authored
> copy lives at
> `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-ae43c33b63a0e0379/.pr-readiness/verification-wave2.md`
> and was copied into the lead's `pensive-kowalevski-be7b32/.pr-readiness/` afterwards.

| PR | Command | Candidate | Verdict |
| --- | --- | --- | --- |
| #1607 | `rocketride diff` | `b2d6d5bda711ddbde084fa8b85bfd619aa6671f2` | **ACCEPT — push-ready** |
| #1581 | `rocketride eval` | `8e7ef7230458003426ec30702c48084241facdd4` | **ACCEPT — push-ready** |
| #1612 | `rocketride otel` | `1d16eed5f0af20c4669b84f288b47bac51dbc322` | **ACCEPT — push-ready** (one report-accuracy correction required before the PR comment goes out) |

There are **no code changes required** in any of the three candidates.

---

## 1. History — all three clean

```
b2d6d5bda  parents: 6f9199758 (approved head) f9a25cbbd (develop)
8e7ef7230  parents: 1b7ed6697 (approved head) f9a25cbbd (develop)
1d16eed5f  parents: 0a5c6f8ce (approved head) f9a25cbbd (develop)
```

- `git merge-base --is-ancestor <head> <candidate>` → true for all three. Approval anchors survive.
- `git rev-list --count <candidate> ^<head> ^<develop>` → **1** for all three. Exactly one new
  commit; no rebase, no rewrite, no squash.
- **Still merges clean against TODAY's develop.** `upstream/develop` has moved twice since the
  briefed target (`f9a25cbbd` → `038ae3dd3` → `617f2f449`, "fix(ai,ui): webhook bodies on an
  unread lane (#2230)"). `git merge-tree --write-tree <candidate> 617f2f449` returns a single
  clean tree for **all three** — no re-sync needed before pushing.

### The merge's human content is exactly the resolution, nothing else

Computed the pure auto-merge tree (`git merge-tree --write-tree <head> <develop>`) and diffed it
against each candidate. That diff *is* the engineer's hand-work:

| PR | auto-merge conflicts | files the human touched | verdict |
| --- | --- | --- | --- |
| #1607 | 6 | 8 = those 6 + `cli/commands/diff.py` + `tests/test_diff_cli.py` (the port) | no stray files |
| #1581 | 6 | 8 = those 6 + `cli/commands/eval.py` + `tests/test_eval_cli.py` | no stray files |
| #1612 | 6 (+1 modify/delete) | 11 = those + `otel.py` + `test_otel_cli.py` + `docs/README-clients.md` (accept delete) + `docs/develop/README-clients.md` (+2) + `otel-bridge.md` (1 line) | no stray files |

**Nothing of develop's was lost.** Total lines removed from develop across the three candidates:

- #1607: 5 — two copies of "All commands accept `--uri` and `--apikey`…", the "two additional
  commands" sentence, and two lines of "Every command accepts connection options…". All
  deliberately rewritten.
- #1581 and #1612: 3 each — `def _add_connection_args(parser)`, its unconditional
  `_add_json_arg(parser)`, and the "two additional commands" sentence. Nothing else.

**The feature cores are byte-identical to the approved heads** (empty diffs, head → candidate):
`src/rocketride/pipediff/**` + `.github/actions/pipe-diff/**` + the three pipediff test files;
`src/rocketride/evals/**`; `src/rocketride/otelbridge/**` + `test_otel_{bridge,mapper,setup}.py`.
The merges touched CLI plumbing and docs only.

---

## 2. The port — minimal, and I could not break it

Read every port hunk in full. **All three ports are mechanical**: `class XCommand(BaseCommand)`
→ module-level `async def run_x(args)`; `self.args` → `args`; `self._helper()` →
`_helper(args)`. Control flow, branch order, messages, and every `return <code>` are unchanged
line-for-line. `--token` disappears from docstrings because develop deleted it.

### Argparse surface, machine-diffed (not eyeballed)

I dumped the complete argparse tree — every action's `option_strings`, `dest`, `nargs`, `const`,
`default`, `choices`, `required`, `metavar`, `type`, action class, and `help`, recursively
through `store`/`app`/`deploy` subparsers — for develop, each approved head, and each candidate.

**develop → candidate: the only delta is the one new subparser.** Not one byte of any of the
**36** upstream parsers changed, in any candidate, or in the three-way integration tree. This is
the hard proof that `json_arg=True` preserves every existing call site (see §4).

**approved head → candidate, per new command:**

| Command | args / defaults / help / nargs / choices | intentional deltas |
| --- | --- | --- |
| `diff` | **identical** (paths, `--git`, `--include-layout`, `--json`, `--markdown` mutually exclusive, `--exit-zero`) | description drops `/--token` (gone from develop); **epilog added** documenting exit codes 0/1/2 — additive, matches develop's own style (`validate` has an epilog at develop `main.py:225`) |
| `eval` | **identical** (`files` nargs=+, `--case`, `--fail-fast`, `--json` store_true, `--junit`) | `--token` dropped; `--uri` default and `--apikey` help now develop's |
| `otel` | **identical** (all 8 flags incl. `--protocol`/`--trace-level` choices) | `--token` dropped; `--uri`/`--apikey` now develop's; **epilog added** (extra + exit codes) |

Confirmed `--token` was dead weight: `grep token` over the three head command modules returns
only a docstring mention in `diff.py` and an unrelated "wildcard token scope" phrase in
`otel.py`. No command read `args.token`.

**One real behavior change vs the approved heads, and it is develop's, not the port's:**
`--uri` default moves from `https://api.rocketride.ai` (`CONST_DEFAULT_WEB_CLOUD`, head's
`add_common_args`) to `http://localhost:5565` (`CONST_DEFAULT_WEB_LOCAL`, develop's
`_add_connection_args`). A bare `rocketride eval spec.eval.json` / `rocketride otel` now targets
the local engine, not cloud. Unavoidable — every develop command shares that helper, and
diverging would be worse. **This is the one place the engineer's "behavior held fixed" claim is
overstated** and it should be said out loud in the PR update comment (see Required corrections).

### Exit paths

Traced each command's returns at the candidate against the head, line for line:

- `diff` (`cli/commands/diff.py`): `_fail` → 2 (:119), `1 if diff.has_semantic_changes else 0`
  (:230), `--exit-zero` → 0. Errors on stderr only; stdout untouched before the report `print`.
- `eval` (`cli/commands/eval.py`): spec error → 2 (:153, before any connect), connect failure →
  2 (:162), JUnit write failure → 2 (:204/:210), `finally: await disconnect_all()` (:220).
- `otel` (`cli/commands/otel.py`): missing extra → 2 (:202, before the client exists), insecure
  transport → 2 (:233), post-start `InsecureTransportError`/`OtelNotInstalledError` → 2
  (:265/:272), `KeyboardInterrupt` → 0, unexpected → 1 (:281), `finally` closes only a client it
  built (:285).

**Not routing through `run_cli_command` is correct, and I verified the stated reason rather than
taking it.** `Output.fail()` returns **1** unconditionally (develop `cli/utils/output.py`), and
`Output.__init__` treats any non-`None`, non-`'-'` value as a **file path** — so
`Output(args.json)` with `diff`/`eval`'s boolean `True` lands in the `file` branch and
`os.path.abspath(True)` raises inside a `finally`. Routing them through the shared runner would
both destroy the 1-vs-2 contracts and crash. **Ruling: the bypass is justified.** See the one
narrow cost in Optional (O3).

### Test files: nothing dropped

Collected node-id sets at head and candidate and diffed them.

| PR | head | candidate | added | removed |
| --- | --- | --- | --- | --- |
| #1607 `test_diff_cli.py` | 22 | 24 | `test_diff_is_registered_exactly_once_alongside_validate`, `test_dispatch_routes_diff_to_run_diff` | **none** |
| #1581 `test_eval_cli.py` | 17 | 20 | `test_eval_is_registered_exactly_once_alongside_validate`, `test_eval_owns_its_own_boolean_json_flag`, `test_validate_keeps_the_shared_json_file_option` | **none** |
| #1612 `test_otel_cli.py` | 23 | 26 | 5 (incl. `test_cli_client_is_built_from_args_and_left_unconnected`, `test_injected_client_is_not_disconnected_by_the_command`) | **2** (see R1) |

`TestCliEval` survives in #1581's `test_cli_integration.py` (auto-merged, engine-bound).

---

## 3. Accepted fixes — all present, all tested, all green

Every fix below was located at the candidate and its named test executed.

### #1612 (all in the byte-identical `otelbridge/` core, invoked from the ported `otel.py`)

| Fix | Location at candidate | Test | Result |
| --- | --- | --- | --- |
| OTLP generic vs signal-specific endpoint precedence | `otelbridge/config.py:332 effective_endpoint`, `:284 redact_endpoint` | `test_otel_bridge.py:179 test_signal_specific_env_left_to_the_sdk_exporters`, `:195 test_generic_endpoint_env_left_to_the_sdk_exporters`, `:209 test_explicit_endpoint_arg_still_wins`, `test_otel_setup.py:146/:191/:201` | pass |
| Transport-security / plaintext-credential guard | `otelbridge/config.py:402 validate_transport_security`, called at `cli/commands/otel.py:230` **before** the client exists (built at :254) | `test_otel_cli.py:492 test_cleartext_credentials_refused_with_exit_2`, `:512 test_insecure_flag_allows_cleartext_and_warns`, `:526 test_loopback_cleartext_still_works`, `test_otel_setup.py:410/:421` | pass |
| Finite run/pipe caps, bounded queues, eviction | `otelbridge/mapper.py:127 MAX_TRACKED_RUNS=1024`, `:138 MAX_TRACKED_PIPES_PER_RUN=256`, `:144 MAX_TRACKED_METRIC_RUNS=4096` | `test_otel_mapper.py:651/:668/:688/:698` | pass |
| Existing event-loop signal handlers preserved | `otelbridge/bridge.py:232-248` (`_loop_owns_signal` → skip, never `add_signal_handler` over an owner; `signal.signal(sig, previous)` restore at :298) | `test_otel_bridge.py:548 test_pre_existing_loop_signal_handler_is_not_stolen`, `:577 test_install_signal_handlers_false_registers_nothing` | pass |
| Shutdown / flush ordering | `otelbridge/bridge.py` teardown, `otelbridge/setup.py` shutdown | `test_otel_bridge.py:328 test_shutdown_closes_spans_before_flushing_exporters`, `test_otel_setup.py:241` | pass |

`pytest -k "…" tests` over that set: **17 passed**. Endpoint redaction also intact
(`otel.py:124 _endpoint_display`, tests `:457`/`:476`).

### #1607

| Fix | Location at candidate | Test | Result |
| --- | --- | --- | --- |
| Type-sensitive JSON equality (bool vs number) | `pipediff/engine.py:445 _json_equal`, `:461-462` bool short-circuit | `test_pipediff_engine.py:429/:449/:466` (source comment at :430 names the `False == 0` trap) | pass — and reproduced live from the installed wheel: `config.n: 1 -> true` |
| Exact layout-noise boundaries + `--include-layout` | `pipediff/engine.py` (ui/viewport), `cli/commands/diff.py:209` | `test_diff_cli.py:364/:378/:391/:404`, `test_pipediff_engine.py:295-386` | pass |
| Safe CLI output / escaping, JSON stdout purity, documented exit codes | `diff.py:105 _fail` (stderr, →2), `:161 _render`, `:230`; `pipediff/reporters.py` control-char + pipe/backtick escaping | `test_diff_cli.py:326 test_json_output_is_pure_and_parseable`, `test_pipediff_reporters.py:108/:128/:333` | pass |
| Composite-Action security | `.github/actions/pipe-diff/action.yml` — **byte-identical to the approved head**; `actions/setup-python@a26af69…`, `actions/github-script@60a0d83…` pinned by full SHA; every untrusted value (`inputs.files`, `install-from`, `cli-version`, `include-layout`, `github.event.pull_request.base.sha`) reaches `run:` **only via `env:`**, never interpolated into a shell body; comment step handles the read-only-token 403 | n/a (YAML) | intact |

`test_diff_cli.py` + 3 pipediff suites: **123 passed**.

### #1581 (all in the byte-identical `evals/` core)

| Fix | Location at candidate | Test | Result |
| --- | --- | --- | --- |
| Path-aware invalid-UTF-8 spec error + documented exit code | `evals/spec.py:458-462` (`f'{path} is not valid UTF-8: {err}'`); mapped to **2** at `cli/commands/eval.py:153`, **before** any connect | `test_eval_spec.py:167 test_non_utf8_file_raises_spec_error` | pass — reproduced live from the installed wheel: exit 2, stdout empty, `Error: smoke/bad.ev.json is not valid UTF-8: …` |
| Bounded judge waits | `evals/runner.py:74 DEFAULT_JUDGE_TIMEOUT_S = 300.0`, `:333 future.result(timeout=judge_timeout)` | `test_eval_runner.py:418 test_stalled_judge_times_out_and_pipelines_are_torn_down`, `:462 test_default_judge_timeout_is_finite` | pass |
| Cancellation across async/thread boundaries | `evals/runner.py:317-336` — `run_coroutine_threadsafe` + `future.cancel()` on expiry, documented as "the worker thread cannot be cancelled" | same two tests | pass |
| Main / judge pipeline teardown | `evals/runner.py:339-350` (judge setup inside the teardown scope) | `test_eval_runner.py:227/:243/:258/:275`, `:364 test_run_pipeline_executes_judge_on_engine_and_tears_down` | pass |

`test_eval_cli.py`: **20 passed**; the evals core: **148 passed**.

---

## 4. `_add_connection_args(*, json_arg=True)` — ruling: **correct, and the safest available option**

- **Default preserves every call site — proven, not asserted.** Full recursive argparse-surface
  dump: all **36** upstream parsers byte-identical develop → each candidate → integration tree.
  The only new parsers are `root.diff`, `root.eval`, `root.otel`.
- **Byte-identical across #1581 and #1612.** `md5` of the 30-line region (`main.py:63-92`) in
  both candidates: `9709b639dcfd02b6e5425e8dcd6b8d4b`. `diff` → empty. Confirmed in the real
  integration merge: git auto-resolved that hunk, the merged `main.py` has exactly one
  `_add_connection_args`, with the keyword.
- **The alternative was worse.** Adopting develop's `--json [FILE]` for `eval` would silently
  turn `eval --json=out.json` from "rejected, exit 2" into "print JSON to stdout" — a semantic
  change to an approved, tested contract. Calling the helper unmodified makes argparse abort on
  the duplicate option string. The keyword is the minimum viable change.
- **#1607 does not touch the helper at all** (verified: its only develop-line removals are doc
  prose), which is why "#1607 first" is the right order.

**Ruling on the port approach overall: ACCEPT.** A keep-both textual resolution would not
import — develop deleted `cli/commands/base.py`, `cli/ui/`, `cli/monitors/`, `status`, `events`
and replaced `RocketRideCLI` with `setup_parser()`/`_dispatch()`. The port is the smallest
change that compiles, and the machine-diffed argparse surface plus the unchanged exit paths show
it did not smuggle behavior in.

---

## 5. Registry, help, packaging — all clean

**Registry** (introspected, not grepped): each candidate registers **11** subcommands,
`['init','login','list','start','stop','upload','validate',<new>,'store','app','deploy']`,
**zero duplicates**. Every upstream command retained with its own args (see §2). One import, one
`__all__` entry, one `_dispatch` branch per command. Integration tree: **13**, zero duplicates.

**Help**: `rocketride --help` and `rocketride <cmd> --help` exit **0 with non-empty stdout for
all 11** commands in each candidate, and **all 13** in the integration tree — including
`validate` and each PR's own command.

**Packaging** — `python -m build` on each candidate, then `pip install` of the wheel into a
throwaway venv, then the **installed console script**:

| | #1607 | #1581 | #1612 |
| --- | --- | --- | --- |
| wheel + sdist build | ok | ok | ok |
| feature module ships | `rocketride/pipediff/{__init__,engine,gitref,model,reporters}.py` | `rocketride/evals/*` | `rocketride/otelbridge/*` |
| data files | — | **`rocketride/evals/templates/judge-default.pipe`** in wheel *and* sdist; readable via `importlib.resources` from the installed package | — |
| console script | `rocketride = rocketride.cli.main:main` (single entry) | same | same |
| installed `--help` | `diff` 0, `validate` 0 | `eval` 0, `validate` 0 | `otel` 0, `validate` 0 |

Live smoke from the installed scripts:

```
rocketride diff old.pipe new.pipe            -> 1   "~ config.n: 1 -> true"   (bool != number)
rocketride diff --json old new  > j.json     -> 1   stdout parses as JSON, stderr 0 bytes
rocketride diff --exit-zero old new          -> 0
rocketride diff missing.pipe new.pipe        -> 2   stdout 0 bytes, stderr "Error: Pipe file not found: …"
rocketride diff <a-directory> new.pipe       -> 2   OSError wrapped into PipeDiffError, not a traceback
rocketride eval bad.ev.json                  -> 2   stdout 0 bytes, path-aware UTF-8 error, no connect attempted
rocketride otel        (extra not installed) -> 2   "requires the OpenTelemetry extra … pip install 'rocketride[otel]'"
```

`otel` extra survives in `[project.optional-dependencies]`; `[tool.setuptools.package-data]`
carries both develop's `py.typed` and #1581's `*.pipe`.

---

## 6. Docs

**`packages/docs/content-static/cli.mdx` intro — each candidate is CORRECT for landing alone.**
develop says "two additional commands (`events`, `list`)"; each candidate says "**three**
additional commands (`events`, `list`, `<cmd>`)". 2 + 1 = 3. Correct for the first land.
Follow-up on lands 2 and 3 (three → four → five) is real and unavoidable: all three rewrite the
same line 18, so **that line conflicts on every subsequent land** — confirmed by my own
`merge-tree` of #1607 + #1581. The engineer's `integration.md` states this explicitly and gives
the final text; it is accurate.

*(Pre-existing develop staleness, not these PRs': that sentence still advertises `events`, and
the core list still names `status`, both of which develop deleted from the Python CLI.
`cli.mdx` also still carries `### status` and `### events` sections. Out of scope here.)*

**#1612's relocation and link fix — correct.** `docs/README-clients.md` deleted (accepting
develop); the PR's sentence re-applied at `docs/develop/README-clients.md:30` with
`../../packages/client-python/docs/otel-bridge.md`, which **resolves** to a real file.
`packages/client-python/docs/otel-bridge.md:427` re-pointed at
`blob/develop/docs/develop/README-clients.md`.

**Dangling-reference sweep** (`docs/README-clients.md`, `cli/commands/base`, `RocketRideCLI`,
`cli/ui`, `cli/monitors`, `BaseCommand`, `*Command`) across all three candidate trees:
**zero** hits except the two comment-only ones in O1 below. `README-clients` references in
#1612 resolve to `docs/develop/README-clients.md` in both places
(`otel-bridge.md:427`, `.github/SUPPORT.md:9`).

**CHANGELOG**: both lines present exactly once, alphabetically ordered
(`- **cli**: … (#1573)` then `- **client-python**: … (#PR)` then `- **database**: …`) in all three.

**`docs/README-python-client.md`**: `## CLI` → `### validate` → the PR's section →
`## Configuration` in all three, matching develop's layout.

---

## 7. Tests — re-run independently, arithmetic reproduced exactly

Python 3.14.3, pytest 9.0.2, `-p no:cacheprovider`, `PYTHONPATH=src:../client-common/python/src`.
CI truth is the compiled engine with a live server; these are local, focused evidence.

**Full offline suite** (`pytest tests`), each candidate vs the develop baseline:

| tree | passed | failed | skipped | errors |
| --- | --- | --- | --- | --- |
| develop `f9a25cbbd` | 82 | 57 | 6 | 21 |
| #1607 | **205** | 57 | 6 | 21 |
| #1581 | **281** | 57 | 6 | 21 |
| #1612 | **214** | 57 | **8** | 21 |

**The 78 FAILED/ERROR node ids are byte-identical to develop's in all three candidates**
(`diff` of the sorted lists → empty). Zero new failures, zero regressions. All 57+21 are
engine-bound (`ConnectionError`, live-server fixtures).

**Skips, honestly**: the 6 baseline skips are "no LLM API key set". #1612's 2 extra are
`test_otel_cli.py:322` and `test_otel_setup.py:301`, both conditioned on *"OTLP gRPC exporter is
installed"* — they skip **because my box has it**; on a box without it they run. That is the
entire difference between my 214 and the engineer's 204-passed figure.

**The engineer's arithmetic, reproduced exactly** with their filter
(`--ignore=tests/RocketRideClient_test.py --ignore=tests/test_cli_integration.py`):

| tree | result | claim |
| --- | --- | --- |
| develop | **70** passed, 21 errors | 70 ok |
| #1607 | **193** = 70 + **123** | 123 ok |
| #1581 | **267** = 70 + **197** | 197 ok |
| #1612 | 202 passed + 2 skipped = **204** = 70 + **134** | 134 ok |
| **integration (#1607→#1581→#1612)** | 522 passed + 2 skipped = **524**, 21 errors | **524 = 70+123+197+134, exact** |

No test lost, duplicated, or shadowed when the three land together.

**Integration merge, reproduced independently.** `merge-tree(#1607, #1581)` → **6 conflicts**
(`CHANGELOG.md`, `docs/README-python-client.md`, `packages/client-python/docs/index.md`,
`cli/commands/__init__.py`, `cli/main.py`, `cli.mdx`) — exactly the set `integration.md` reports.
The engineer's throwaway integration commit `448e90926` verified: 13 subcommands, zero
duplicates, all 13 `--help` exit 0, all 36 upstream parsers unchanged, 524.

**ruff with the repo config** (root `pyproject.toml`, `select=["E","F","Q","D"]`,
`quote-style="single"`, `line-length=120`), run on `packages/client-python` from each tree root:

| | `ruff check` | `ruff format --check` |
| --- | --- | --- |
| #1607 | All checks passed! | 94 files already formatted |
| #1581 | All checks passed! | 98 files already formatted |
| #1612 | All checks passed! | 94 files already formatted |

---

## 8. Findings

### REQUIRED (report/comment text only — no code change)

**R1 — #1612: the changes report under-declares the removed tests.**
`conflict-resolutions-cli.md` and `prs/1612-changes.md` name **one** replaced test
(`test_events_still_requires_token_but_otel_does_not`). The candidate removes **two**: that one
**and** `test_run_routes_otel_without_requiring_token` (head `test_otel_cli.py:347`). Both
asserted on machinery develop deleted (the `--token` flag and the `status/stop/events` token
check), and both are covered by the replacement
`test_dispatch_routes_bare_otel_without_requiring_a_token` (candidate `test_otel_cli.py:362`,
asserts `not hasattr(args, 'token')` and routes through the real `_dispatch`). **Coverage is not
lost** — but the PR comment must say "23 → 26: 2 removed (both asserting on deleted machinery),
5 added", not "1 replaced". Under-declaring a removed test in a PR whose reviewer already
approved it is exactly the thing that gets an approval pulled.

**R2 — all three: disclose the `--uri` default change.**
`eval` and `otel` inherit develop's `_add_connection_args`, so their `--uri` default moves
`https://api.rocketride.ai` → `http://localhost:5565` and `--apikey`'s help text changes. This
is a user-visible change from the state dsapandora approved. It is correct (develop-wide
convention) and should not be reverted, but "behavior held fixed" is not accurate without this
caveat. One sentence in each PR comment.

### OPTIONAL

**O1 — comment-only references to a module develop deleted.**
`c1607 packages/client-python/src/rocketride/pipediff/reporters.py:46,48,69` and
`c1581 packages/client-python/src/rocketride/evals/reporters.py:66` point readers at
`rocketride/cli/ui/colors.py`, which develop removed. Comments only — no import, no link, no
functional impact; develop itself has **zero** `cli/ui` references, so these are the only ones in
the tree. Trade-off: fixing them dirties files that are currently **byte-identical to the
approved heads**, which is the property that makes these merges easy to review. Recommend a
follow-up PR, or a reviewer-blessed one-word tweak ("the CLI's former `ui/colors` module").

**O2 — `diff`'s section position drifts in `cli.mdx`.** #1607 puts `### diff` last (after
`store`); #1581/#1612 insert theirs between `list` and `store`. Cosmetic; the integrated page
ends with `diff`. Worth normalizing while hand-editing the intro count on land 2/3.

**O3 — `diff` and `eval` have no catch-all; every other develop command does.**
Because they bypass `run_cli_command`, a genuinely unexpected exception surfaces as a raw
traceback rather than develop's `Error: <message> — <hint>` (`otel` is fine — it has
`except Exception → 1` at `otel.py:281`). At the approved heads, `main()` had a top-level
`except Exception: print("Operation failed: …"); sys.exit(1)`; develop's `main()` catches only
`KeyboardInterrupt`. The exposed surface is narrow — I probed it and `load_pipe` already wraps
`OSError` into `PipeDiffError` (a directory argument gives a clean `Error:` + exit 2), and
`eval` catches spec, connect, per-spec and JUnit failures. If the lead wants it closed, the
minimal fix that respects both contracts is a trailing `except Exception as err: return
_fail(str(err))` in `run_diff` and the equivalent → **2** in `run_eval` (never 1 — `diff`
reserves 1 for "changes found", `eval` for "a case failed"). Not required for this land.

### Challenges I raised and had to drop

- *"The port silently changed an exit code or a flag."* — Killed by the recursive
  argparse-surface diff (36/36 upstream parsers unchanged; new parsers identical to head bar
  `--token`/epilog) and by line-by-line comparison of every `return` in the three command bodies.
- *"`json_arg=True` breaks an upstream command's `--json`."* — Killed by the same dump plus the
  integration tree.
- *"The `otel` port opens a socket before the missing-extra guard."* — Killed: the head's CLI
  also only *constructed* the client (`main.py:665`, no `.connect()`); the candidate constructs
  it at `otel.py:254`, strictly **after** both guards, and the bridge owns connecting. Verified
  live: bare `rocketride otel` without the extra exits 2 with no connection attempt.
- *"Dropping the head's `on_event`/`on_connected` callbacks from the eval/otel client loses
  behavior."* — Killed: `evals/runner.py` never uses `on_event`; the bridge installs its own
  (`bridge.py:199-223`, preserving and restoring any previous handler); the head's callbacks fed
  the `cli/ui` display develop deleted.
- *"A test was quietly dropped."* — Landed once, and only for #1612 (R1): two removed, both on
  deleted machinery, coverage replaced. #1607 and #1581 dropped nothing.

---

## Push-ready verdict

All three candidates are **push-ready as-is**. They merge clean against today's `upstream/develop`
(`617f2f449`), carry no code defects I could find, keep every accepted fix with its named test
green, drop no upstream behavior, and reproduce the engineer's numbers exactly.

Land in the stated order **#1607 → #1581 → #1612**; #1607 is the only one that leaves
`_add_connection_args` alone, so it is the cleanest first. Lands 2 and 3 will each conflict in
the same six files — additive resolutions everywhere except `cli.mdx` line 18, whose count and
list must be hand-bumped three → four → five.

Before the PR comments go out: apply **R1** (#1612 removed-test count) and **R2** (`--uri`
default disclosure).
