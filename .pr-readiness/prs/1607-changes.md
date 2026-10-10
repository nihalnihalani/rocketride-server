# PR #1607 — `rocketride diff` — develop-sync candidate

| | |
| --- | --- |
| Branch (in my worktree) | `pr1607-develop-sync` |
| Candidate SHA | `b2d6d5bda711ddbde084fa8b85bfd619aa6671f2` |
| Parents | `6f9199758160457114a568bb53e68d1077fa8077` (PR head) · `f9a25cbbd73f8feb9fbc99ea3aeb5bd241dafc1e` (develop) |
| Worktree | `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-a3f470621685a0c1d/wt/pr1607` |
| Push line for the lead | `git push origin b2d6d5bda711ddbde084fa8b85bfd619aa6671f2:refs/heads/feat/RR-1606-pipe-diff` |
| Descendant of the current remote head? | yes (`git merge-base --is-ancestor refs/review-pr/1607 HEAD` → true) |

## What changed relative to the approved head

Only the merge with develop. The PR's own product code is untouched apart from the CLI
adapter layer that develop's rewrite forced.

### Files carried over unchanged (proved byte-identical)

`git diff refs/review-pr/1607 -- .github/actions/pipe-diff examples packages/client-python/src/rocketride/pipediff` → **empty**.

That is the entire `pipediff` engine (`engine.py`, `gitref.py`, `model.py`, `reporters.py`,
`__init__.py`), the composite action (`action.yml`, `README.md`), and both example docs.

### Files changed by the merge

| File | Change |
| --- | --- |
| `packages/client-python/src/rocketride/cli/commands/diff.py` | Ported `class DiffCommand(BaseCommand)` → `async def run_diff(args)`. `BaseCommand` no longer exists on develop. `_should_use_color`, `_fail`, `_resolve_inputs`, `_render` are now module functions taking `args`. Behavior is byte-for-byte equivalent: same exit codes, same stdout/stderr split, same reporter selection, same `_EMPTY_PIPE` handling for a `--git` ref that lacks the file. **Not** wired to `run_cli_command` — that runner would build `Output(args.json)` from a boolean and would map errors to exit 1, breaking the documented 1 = "changes found" / 2 = "error" contract. |
| `packages/client-python/src/rocketride/cli/main.py` | Develop's `setup_parser()`/`_dispatch()` taken whole; `diff` re-registered after `validate` with the PR's exact arguments plus an exit-code `epilog`; one docstring line; one `_dispatch` branch; one local import. |
| `packages/client-python/src/rocketride/cli/commands/__init__.py` | `from .diff import run_diff` + `'run_diff'` in `__all__`, alphabetically placed. |
| `packages/client-python/tests/test_diff_cli.py` | Same 22 tests, retargeted at `run_diff` and `cli_main.setup_parser()`. **Added 2**: `test_diff_is_registered_exactly_once_alongside_validate` and `test_dispatch_routes_diff_to_run_diff`. |
| `CHANGELOG.md`, `docs/README-python-client.md`, `packages/client-python/docs/index.md`, `packages/docs/content-static/cli.mdx` | Both this PR's and develop's entries/sections kept, `validate` first. |

Net diff over develop: **20 files**, exactly the PR's own 20. No develop content dropped.

## Accepted-fix survival

| Accepted fix | Survives? | Evidence in code | Regression test | Live check |
| --- | --- | --- | --- | --- |
| Type-sensitive JSON equality (boolean vs number) | yes | `pipediff/engine.py`, unchanged | `test_pipediff_engine.py` (57 tests, all pass) | `diff t_old.pipe t_new.pipe` with `flag: 1` → `flag: true` prints `~ config.flag: 1 -> true`, exit 1 |
| Exact layout-noise boundaries incl. `--include-layout` | yes | `pipediff/engine.py` + `run_diff` passes `include_layout` | `test_diff_cli.py::test_layout_only_hidden_by_default_exit_0`, `::test_include_layout_surfaces_ui_fields_exit_1`, `::test_viewport_only_hidden_by_default_exit_0`, `::test_include_layout_surfaces_viewport_fields_exit_1` | real git repo: layout-only move → exit 0 with no `ui.*` lines; `--include-layout` → exit 1 with `ui.position.x/y` |
| Safe CLI output/escaping | yes | `pipediff/reporters.py::render_markdown` (pipe/backtick escaping), unchanged; `_fail` writes only to stderr | `test_pipediff_reporters.py` (27), `test_diff_cli.py::test_markdown_output` | `--markdown` output renders the escaped table |
| JSON stdout purity | yes | `run_diff` prints the report last; every error path returns via `_fail` → stderr | `test_diff_cli.py::test_json_output_is_pure_and_parseable` (asserts `captured.err == ''`) | `diff --git HEAD rag.pipe --json` parsed with `json.load` straight from stdout |
| Documented exit codes (0/1/2) | yes | `run_diff` returns 0/1/2; `epilog` now states them in `--help` | 9 exit-code tests in `test_diff_cli.py` | bad git ref → exit 2 with **empty stdout**; `--exit-zero` with changes → 0; `--exit-zero` with a load error → still 2 |
| Secure input handling in the composite action (pinned deps, quoted shell args, no privileged execution of untrusted PR input) | yes | `.github/actions/pipe-diff/action.yml` byte-identical: `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065`, `actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea`, every `${{ inputs.* }}` passed through `env:` rather than interpolated into `run:`, `set -euo pipefail`, `"${VAR}"` quoting throughout, and an explicit warning that `install-from` executes build code and must never point at PR-head code in a `pull_request_target` workflow | none (YAML) — covered by byte-identity | inspected |

## Test tally

| Scope | Result |
| --- | --- |
| PR's own files | 123 passed (`test_diff_cli` 24 · `test_pipediff_engine` 57 · `test_pipediff_gitref` 15 · `test_pipediff_reporters` 27) |
| `packages/client-python` offline suite | 193 passed, 21 engine-bound errors (= 70 develop baseline + 123) |
| `ruff check` / `ruff format --check` | clean / 97 files formatted |
| Wheel + sdist | built; `pipediff` package and `cli/commands/diff.py` present; console script present |

## Not verifiable here

- `test_cli_integration.py` and `RocketRideClient_test.py` — engine-bound; need
  `./builder client-python:test` (C++ engine + live server). Unavailable, not passing.
- `builder docs:build` — needs `pnpm install` + the engine build chain.
- The composite action end to end — needs a GitHub Actions runner.
