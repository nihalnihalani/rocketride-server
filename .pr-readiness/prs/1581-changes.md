# PR #1581 — `rocketride eval` — develop-sync candidate

| | |
| --- | --- |
| Branch (in my worktree) | `pr1581-develop-sync` |
| Candidate SHA | `8e7ef7230458003426ec30702c48084241facdd4` |
| Parents | `1b7ed6697f1f28d11aa794ae4008f9d59c596ccd` (PR head) · `f9a25cbbd73f8feb9fbc99ea3aeb5bd241dafc1e` (develop) |
| Worktree | `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-a3f470621685a0c1d/wt/pr1581` |
| Push line for the lead | `git push origin 8e7ef7230458003426ec30702c48084241facdd4:refs/heads/feat/RR-1578-eval-runner` |
| Descendant of the current remote head? | yes |

## What changed relative to the approved head

### Files carried over unchanged (proved byte-identical)

`git diff refs/review-pr/1581 -- packages/client-python/src/rocketride/evals examples` → **empty**.

That is the whole `evals` package (`spec.py`, `runner.py`, `judge.py`, `assertions.py`,
`reporters.py`, `templates/judge-default.pipe`, `__init__.py`) and both example files.

### Files changed by the merge

| File | Change |
| --- | --- |
| `packages/client-python/src/rocketride/cli/commands/eval.py` | Ported `class EvalCommand(BaseCommand)` → `async def run_eval(args)`. The old code reached the client through `self.cli.client` / `self.cli.connect()`, which no longer exist; it now calls `utils.common.connect_client(args.uri, args.apikey)`. `_expand_files` became a module function. `disconnect_all()` runs in a `finally` that wraps the connect attempt, so a client registered by a failing `connect_client` is still cleaned up. **Not** wired to `run_cli_command`: that runner would read the boolean `--json` as a filename and would collapse the 1-vs-2 exit-code distinction. |
| `packages/client-python/src/rocketride/cli/main.py` | Develop's `setup_parser()`/`_dispatch()` taken whole; `eval` re-registered after `validate` with the PR's exact arguments and description; one docstring line; one `_dispatch` branch; one local import. **Plus** `_add_connection_args(parser, *, json_arg: bool = True)` — see below. |
| `packages/client-python/src/rocketride/cli/commands/__init__.py` | `from .eval import run_eval` + `'run_eval'` in `__all__`, alphabetically placed. |
| `packages/client-python/tests/test_eval_cli.py` | Same 17 tests, retargeted: `run_cli()` now patches `connect_client` in the **eval module's** namespace (it binds the name at import time) and drives `cli_main.setup_parser()` + `_dispatch`, mirroring develop's own `test_validate_cli.py`. **Added 3** in `TestEvalRegistration`: registered-exactly-once vs `validate`, `eval --json` stays boolean and `--json=FILE` is rejected, and `validate --json[=FILE]` keeps the shared envelope. |
| `packages/client-python/tests/test_cli_integration.py` | Auto-merged; the PR's `TestCliEval` class survives untouched (it shells out to the real binary, so the architecture change is invisible to it). |
| `packages/client-python/pyproject.toml` | Auto-merged; `"rocketride.evals.templates" = ["*.pipe"]` package-data line intact. |
| `CHANGELOG.md`, `docs/README-python-client.md`, `packages/client-python/docs/index.md`, `packages/docs/content-static/cli.mdx` | Both this PR's and develop's entries/sections kept, `validate` first. |

### The one design decision worth a reviewer's eye

`eval` declares its own boolean `--json` (a whole JSON report on stdout). develop's
`_add_connection_args` unconditionally adds `--json [FILE]`. Calling it as-is aborts with
`argparse.ArgumentError: conflicting option string: --json`; adopting develop's form would
silently change `eval --json=out.json` from **rejected** to **"print JSON to stdout"**.

Resolution: one keyword on develop's helper —

```python
def _add_connection_args(parser: argparse.ArgumentParser, *, json_arg: bool = True) -> None:
    ...
    if json_arg:
        _add_json_arg(parser)
```

Default `True`, so **no existing call site changes**. `eval` calls it with `json_arg=False`
and then declares its own `--json`. #1612 needs the identical keyword and the two are written
byte-identically, so the second merge auto-resolves that hunk (confirmed in the integration
check).

Net diff over develop: **25 files**, exactly the PR's own 25. No develop content dropped.

## Accepted-fix survival

| Accepted fix | Survives? | Evidence in code | Regression test | Live check |
| --- | --- | --- | --- | --- |
| Path-aware invalid-UTF-8 spec errors with the documented exit code | yes | `evals/spec.py::load_spec` raises `EvalSpecError` naming the file; `run_eval` prints `Error: {err}` and returns **2** before any connection | `test_eval_spec.py` (58, UTF-8 cases included); `test_eval_cli.py::test_spec_parse_error_exits_2_without_connecting` (asserts `fake.calls == []` and `not fake.connected`), `::test_spec_validation_error_exits_2`, `::test_missing_spec_file_exits_2`, `::test_one_broken_spec_blocks_the_run` | `rocketride eval <0xff-in-input>.eval.json` → exit 2, stderr `Error: /abs/path/badutf8.eval.json is not valid UTF-8: 'utf-8' codec can't decode byte 0xff in position 60: invalid start byte` |
| Bounded judge waits | yes | `evals/runner.py`: `DEFAULT_JUDGE_TIMEOUT_S`, `future.result(timeout=judge_timeout)`, `TimeoutError(f'judge pipeline {pipeline_path!r} did not answer within {judge_timeout}s')` — unchanged | `test_eval_runner.py` (20), `test_eval_judge.py` (34) | — (no engine) |
| Cancellation across async/thread boundaries | yes | `evals/runner.py`: assertions run in `asyncio.to_thread`; the judge coroutine is driven from that non-cancellable worker via a future that is `future.cancel()`-ed on timeout, with the reasoning documented in the module comments — unchanged | `test_eval_runner.py` | — |
| Teardown of main and judge pipelines | yes | `evals/runner.py::run_spec` always terminates — unchanged | `test_eval_runner.py`; `test_eval_cli.py::test_all_cases_pass_exits_0` asserts the exact call order `['use','chat','chat','terminate']`, and `::test_pipeline_start_failure_with_passing_spec_exits_1` proves a spec-level failure does not skip the remaining specs' teardown | — |
| Connection failure is exit 2, not 1 (CLI contract) | yes | `run_eval` catches the `connect_client` failure locally rather than letting a catch-all map it to 1 | `test_eval_cli.py::test_connection_failure_exits_2` | `rocketride eval ok.eval.json --uri http://127.0.0.1:1` → exit **2**, stderr `Error: Unable to connect to server: [Errno 61] Connect call failed ('127.0.0.1', 1)` |
| JUnit report contract (`--junit`, unwritable path → 2) | yes | `run_eval` unchanged logic | `test_eval_cli.py::test_junit_report_written_alongside_human_output`, `::test_unwritable_junit_path_exits_2` | — |

## Test tally

| Scope | Result |
| --- | --- |
| PR's own files | 197 passed (`test_eval_cli` 20 · `test_eval_spec` 58 · `test_eval_runner` 20 · `test_eval_judge` 34 · `test_eval_assertions` 45 · `test_eval_reporters` 20) |
| `packages/client-python` offline suite | 267 passed, 21 engine-bound errors (= 70 develop baseline + 197) |
| `ruff check` / `ruff format --check` | clean / 101 files formatted |
| Wheel + sdist | built; `evals` package **including `templates/judge-default.pipe`** present; console script present |

## Not verifiable here

- `test_cli_integration.py::TestCliEval` (the PR's own 2 integration cases) and
  `RocketRideClient_test.py` — engine-bound; need `./builder client-python:test`.
  Unavailable, not passing.
- Any `llm_judge` path end to end — needs an engine and `ROCKETRIDE_OPENAI_KEY`.
- `builder docs:build`.
