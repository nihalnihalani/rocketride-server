# Validation log — CLI PRs #1612 / #1607 / #1581

Author: sdk-implementation-engineer. Nothing pushed, nothing posted.
Date: 2026-09-10. Host: darwin 25.5.0 (arm64).

## Environment (identical per worktree)

| Item | Value |
| --- | --- |
| Python | 3.12.12 (`uv venv --python 3.12`, CPython from `/opt/homebrew/opt/python@3.12`) |
| uv | 0.9.26 |
| Install | `uv pip install -e 'packages/client-python[dev,test]'` (+ `,otel` for #1612 and the integration tree) |
| Extra install | `pytest-timeout` — `pyproject.toml` sets `timeout` under `[tool.pytest.ini_options]` but neither the `dev` nor `test` extra ships the plugin (pre-existing on develop; without it pytest warns `Unknown config option: timeout`) |
| pytest | 9.1.1, `asyncio_mode = auto`, plugins: asyncio 1.4.0, cov 7.1.0, timeout 2.4.0 |
| ruff | 0.16.6 (repo config: root `pyproject.toml`) |
| `PYTHONPATH` for CLI smoke | `packages/client-common/python/src` — `rocketride_common` sits beside `rocketride` only in the built wheel; in the source tree they are apart. `tests/conftest.py` documents exactly this and patches `sys.path` for pytest; the console script gets no such help, so `rocketride --help` from a source install fails with `ModuleNotFoundError: rocketride_common` **on plain develop too**. Pre-existing on develop, environmental, not caused by these merges. |

## Baseline: develop @ `f9a25cbbd`, no PR content

- cwd `<agent-wt>/wt/baseline-develop/packages/client-python`
- `python -m pytest tests/ -q --timeout=90 --ignore=tests/RocketRideClient_test.py --ignore=tests/test_cli_integration.py`
- **70 passed, 21 errors**, 1.63 s, exit 1
- All 21 errors are `ConnectionError` from the `client` fixture in `conftest.py` (`test_deploy.py`, `test_tool.py`, `test_analytics.py`, `test_database.py`, …): they need a live engine on `localhost:5565`.
- `RocketRideClient_test.py` and `test_cli_integration.py` are excluded because they are wholly engine-bound (57 failures when included; `client-python:test` in `scripts/tasks.js` builds the C++ engine and brackets the suite with a real server). **Engine-bound: unavailable here — never counted as passes.**

Every "N passed" below decomposes exactly as `70 + <PR tests>`, which is the no-regression / no-dropped-test proof.

---

## PR #1607 — candidate `b2d6d5bda711ddbde084fa8b85bfd619aa6671f2` (`pr1607-develop-sync`)

head `6f9199758` · target `f9a25cbbd`

| # | Command | cwd | Result |
| --- | --- | --- | --- |
| 1 | `git merge --no-commit --no-ff upstream/develop` | `wt/pr1607` | 6 conflicts (CHANGELOG, README-python-client, docs/index.md, cli/commands/__init__.py, cli/main.py, cli.mdx) |
| 2 | `python -m pytest tests/test_diff_cli.py tests/test_pipediff_{engine,gitref,reporters}.py -q` | `wt/pr1607/packages/client-python` | **123 passed**, 0.26 s, exit 0 (test_diff_cli 24 · engine 57 · gitref 15 · reporters 27) |
| 3 | `python -m pytest tests/ -q --timeout=90 --ignore=RocketRideClient_test.py --ignore=test_cli_integration.py` | same | **193 passed, 21 errors**, 1.51 s (= 70 baseline + 123) |
| 4 | `python -m ruff check packages/client-python` | `wt/pr1607` | `All checks passed!` exit 0 |
| 5 | `python -m ruff format --check packages/client-python` | same | `97 files already formatted` exit 0 |
| 6 | `rocketride --help` | same | exit 0; lists init, login, list, start, stop, upload, **validate**, **diff**, store, app, deploy |
| 7 | `rocketride validate --help` | same | exit 0; `--uri --apikey --json [FILE] --source files…` + exit-code epilog intact |
| 8 | `rocketride diff --help` | same | exit 0; `--git --include-layout --json|--markdown --exit-zero`, no `--uri`/`--apikey`/`--token` in the namespace |
| 9 | `python -m build` | `wt/pr1607/packages/client-python` | wheel + sdist built; wheel contains `rocketride/pipediff/{__init__,engine,gitref,model,reporters}.py`, `cli/commands/diff.py`, `cli/commands/validate.py`; `entry_points.txt` → `rocketride = rocketride.cli.main:main` |

### Real-git-repo `--git` smoke (brief §"not mocks")

Temporary repo under the scratchpad: `git init`, commit `rag.pipe`, mutate, run the installed console script.

| Case | Expected | Got |
| --- | --- | --- |
| unchanged vs `HEAD` | 0, "No semantic changes." | 0 ✓ |
| `strlen 512→1024` vs `HEAD` | 1, config change reported | 1 ✓ |
| same, `--json` | 1, stdout = exactly one JSON doc | 1 ✓ (`json.load` succeeded; keys `edges/nodes/summary/viewport`; `summary.has_semantic_changes=true`) |
| layout-only move, default | 0, coarse "Layout: changed", no `ui.*` lines | 0 ✓ |
| layout-only move, `--include-layout` | 1, `ui.position.x/y` enumerated | 1 ✓ |
| `--git no-such-ref` | 2, **empty stdout**, error on stderr | 2 ✓, stdout `[]` ✓ |
| `config.flag: 1` vs `true` (two files) | 1 — type-sensitive equality | 1 ✓ (`~ config.flag: 1 -> true`) |
| `--exit-zero` with changes | 0 | 0 ✓ |

`test_pipediff_gitref.py::test_resolve_git_ref_real_repository` also drives a real temporary
repository (the other 14 cases in that file stub `subprocess.run` deliberately).

---

## PR #1581 — candidate `8e7ef7230458003426ec30702c48084241facdd4` (`pr1581-develop-sync`)

head `1b7ed6697` · target `f9a25cbbd`

| # | Command | cwd | Result |
| --- | --- | --- | --- |
| 1 | `git merge --no-commit --no-ff upstream/develop` | `wt/pr1581` | same 6 conflicts |
| 2 | `python -m pytest tests/test_eval_{cli,spec,runner,judge,assertions,reporters}.py -q --timeout=90` | `wt/pr1581/packages/client-python` | **197 passed**, 0.33 s, exit 0 (cli 20 · spec 58 · runner 20 · judge 34 · assertions 45 · reporters 20) |
| 3 | `python -m pytest tests/ -q --timeout=90 --ignore=…` | same | **267 passed, 21 errors**, 1.72 s (= 70 + 197) |
| 4 | `python -m ruff check packages/client-python` | `wt/pr1581` | `All checks passed!` exit 0 |
| 5 | `python -m ruff format --check packages/client-python` | same | `101 files already formatted` exit 0 |
| 6 | `rocketride --help` | same | exit 0; **validate** and **eval** both listed once |
| 7 | `rocketride validate --help` | same | exit 0; `--json [FILE]` intact |
| 8 | `rocketride eval --help` | same | exit 0; `--uri --apikey --case --fail-fast --json --junit files…`; description carries the 0/1/2 contract |
| 9 | `rocketride eval <missing>.eval.json --uri http://127.0.0.1:1` | same | **exit 2**, stderr `Error: Eval spec file not found: …`, no connection attempted |
| 10 | `rocketride eval <invalid-utf8>.eval.json --uri http://127.0.0.1:1` | same | **exit 2**, stderr `Error: <abs path> is not valid UTF-8: 'utf-8' codec can't decode byte 0xff in position 60…` — path-aware, documented code |
| 11 | `rocketride eval <valid>.eval.json --uri http://127.0.0.1:1 --apikey k` | same | **exit 2** (not 1), stderr `Error: Unable to connect to server: [Errno 61] Connect call failed` |
| 12 | `python -m build` | `wt/pr1581/packages/client-python` | wheel + sdist; wheel contains `rocketride/evals/{__init__,assertions,judge,reporters,runner,spec}.py` **and** `evals/templates/judge-default.pipe` (the PR's `package-data` line survived); console script present |

---

## PR #1612 — candidate `1d16eed5f0af20c4669b84f288b47bac51dbc322` (`pr1612-develop-sync`)

head `0a5c6f8ce` · target `f9a25cbbd`

| # | Command | cwd | Result |
| --- | --- | --- | --- |
| 1 | `git merge --no-commit --no-ff upstream/develop` | `wt/pr1612` | 6 content conflicts + 1 **modify/delete** (`docs/README-clients.md`) |
| 2 | `python -m pytest tests/test_otel_{cli,bridge,mapper,setup}.py -q --timeout=90` (no otel extra) | `wt/pr1612/packages/client-python` | 60 passed, **3 skipped** — mapper/setup need `opentelemetry` |
| 3 | same, after `uv pip install -e 'packages/client-python[dev,test,otel]'` | same | **134 passed**, 1.29 s, exit 0 (cli 26 · bridge 35 · mapper 46 · setup 27) |
| 4 | `python -m pytest tests/ -q --timeout=120 --ignore=…` | same | **204 passed, 21 errors**, 1.89 s (= 70 + 134) |
| 5 | `python -m ruff check packages/client-python` | `wt/pr1612` | `All checks passed!` exit 0 |
| 6 | `python -m ruff format --check packages/client-python` | same | `98 files already formatted` exit 0 |
| 7 | `rocketride --help` | same | exit 0; **validate** and **otel** both listed once |
| 8 | `rocketride validate --help` | same | exit 0; unchanged |
| 9 | `rocketride otel --help` | same | exit 0; `--uri --apikey --endpoint --protocol{http,grpc} --service-name --headers --include-content --insecure --no-metrics --trace-level{none,metadata,summary,full}`; **no `--json`**; epilog carries the extra hint + 0/1/2 codes |
| 10 | `rocketride otel --endpoint http://collector.example:4318 --headers 'x-api-key=SUPERSECRET'` | same | **exit 2**; stderr names the header **key** and the refusal; the **value never appears** (`grep -c SUPERSECRET` → 0) |
| 11 | same `+ --insecure` | same | banner printed, `WARNING: --insecure is set…` on stderr, value still absent; proceeds to connect (then exit 2 on the unreachable `--uri`, as designed) |
| 12 | `rocketride otel --endpoint http://localhost:4318 --headers 'Authorization=Basic SECRETVAL'` | same | loopback cleartext allowed; banner printed; `SECRETVAL` absent from stdout+stderr |
| 13 | `rocketride otel --endpoint 'https://svcuser:sup3rs3cret@collector.example:4318/v1/traces?sig=DEADBEEF'` | same | banner shows `https://collector.example:4318/v1/traces?<redacted>`; `svcuser`, `sup3rs3cret`, `DEADBEEF` all absent |
| 14 | `rocketride otel --trace-level summary` | same | prints the informational note including `pipelineTraceLevel='summary'` before the banner |
| 15 | `python -m build` | `wt/pr1612/packages/client-python` | wheel + sdist; wheel contains `rocketride/otelbridge/{__init__,bridge,config,mapper,setup}.py` and `cli/commands/otel.py`; METADATA `Provides-Extra: dev, otel, test` with `opentelemetry-sdk>=1.27.0` and `opentelemetry-exporter-otlp-proto-http>=1.27.0` under `extra == "otel"` |

All runs above used the console script from the venv, i.e. through `setup_parser()` +
`_dispatch()`, not by calling the command function directly.

---

## Accepted-fix survival

Every fix below was verified **in the merged candidate**, both in code and via its regression
test. None was re-implemented — the business-logic packages are byte-identical to the PR heads.

### #1612 (otelbridge/ untouched: `git diff refs/review-pr/1612 -- …/otelbridge` empty)

| Accepted fix | Where it lives | Regression test(s) | Status |
| --- | --- | --- | --- |
| OTLP generic vs signal-specific endpoint precedence | `otelbridge/config.py` | `test_otel_bridge.py::TestOtelConfig::{test_defaults_when_no_args_no_env, test_signal_specific_env_left_to_the_sdk_exporters, test_env_used_when_args_absent, test_generic_endpoint_env_left_to_the_sdk_exporters, test_explicit_endpoint_arg_still_wins, test_args_override_env}` | pass |
| Transport-security validation (plaintext-credential guard) | `otelbridge/config.py::validate_transport_security` | `test_otel_bridge.py::{test_credential_header_over_remote_http_is_refused, test_loopback_http_is_allowed, test_https_is_allowed, test_non_credential_headers_over_http_are_allowed, test_env_headers_are_checked_too, test_signal_specific_env_endpoint_is_checked, test_metrics_endpoint_ignored_when_metrics_disabled, test_default_endpoint_is_loopback_and_allowed, test_scheme_less_grpc_is_tls_unless_insecure_env_says_otherwise, test_allow_insecure_opt_out, test_allow_insecure_resolved_from_flag_and_env}`; CLI side `test_otel_cli.py::TestOtelTransportSecurity` (5) | pass + live smoke #10–#13 |
| Finite resource limits (run/pipe caps, bounded queues, eviction) | `otelbridge/mapper.py` | `test_otel_mapper.py::{test_tracked_run_cap_evicts_least_recently_eventful_run, test_tracked_pipe_cap_evicts_least_recently_eventful_pipe, test_tracked_pipe_cap_bounds_a_never_ending_run, test_metrics_last_counts_bounded_lru, test_include_content_truncates_to_cap, test_error_leave_with_content_truncates_string_errors_to_cap}` | pass |
| Preservation of existing event-loop signal handlers | `otelbridge/bridge.py::_loop_owns_signal` + the register/restore block | `test_otel_bridge.py::{test_pre_existing_loop_signal_handler_is_not_stolen, test_install_signal_handlers_false_registers_nothing}` | pass |
| Shutdown / flush | `otelbridge/bridge.py` | `test_otel_bridge.py::{test_shutdown_closes_spans_before_flushing_exporters, test_startup_connect_failure_returns_2, test_subscription_failure_returns_2, test_reconnects_with_backoff_without_resubscribing, test_chains_and_restores_previous_event_handler}` | pass |
| CLI-side: guard before connect | `cli/commands/otel.py` (ported) | `test_otel_cli.py::TestMissingExtraGuard::test_exits_2_with_hint_before_connecting` (asserts `client.connect_calls == 0`) + new `TestCliRouting::test_cli_client_is_built_from_args_and_left_unconnected` | pass |

### #1607 (pipediff/ and the composite action untouched)

| Accepted fix | Where | Regression test(s) | Status |
| --- | --- | --- | --- |
| Type-sensitive JSON equality (bool vs number) | `pipediff/engine.py` | `test_pipediff_engine.py` (bool/number cases) | pass; live smoke case 7 (`1 -> true` reported, exit 1) |
| Exact layout-noise boundaries incl. `--include-layout` | `pipediff/engine.py` + CLI passthrough | `test_diff_cli.py::{test_layout_only_hidden_by_default_exit_0, test_include_layout_surfaces_ui_fields_exit_1, test_viewport_only_hidden_by_default_exit_0, test_include_layout_surfaces_viewport_fields_exit_1}` | pass; live smoke cases 4–5 |
| Safe CLI output/escaping, JSON stdout purity, documented exit codes | `cli/commands/diff.py` (ported), `pipediff/reporters.py` | `test_diff_cli.py::{test_json_output_is_pure_and_parseable, test_markdown_output, test_missing_file_exit_2, test_invalid_json_exit_2, test_non_pipe_object_exit_2, test_wrong_positional_count_exit_2, test_no_files_exit_2, test_git_resolver_error_exit_2, test_exit_zero_does_not_mask_errors}` | pass; live smoke cases 3, 6 |
| Secure input handling in the composite GitHub Action | `.github/actions/pipe-diff/action.yml` | no unit test (YAML); verified by inspection **and** by byte-identity with the approved head | unchanged: pinned action SHAs (`actions/setup-python@a26af69…`, `actions/github-script@60a0d83…`), every `${{ }}` routed through `env:` instead of interpolated into `run:`, `set -euo pipefail`, quoted expansions, `install-from` documented as executing untrusted build code and warned off `pull_request_target` |

### #1581 (evals/ untouched)

| Accepted fix | Where | Regression test(s) | Status |
| --- | --- | --- | --- |
| Path-aware invalid-UTF-8 spec errors with the documented exit code | `evals/spec.py::load_spec` → `EvalSpecError`, surfaced by `run_eval` as 2 | `test_eval_spec.py` (UTF-8 cases); `test_eval_cli.py::{test_spec_parse_error_exits_2_without_connecting, test_spec_validation_error_exits_2, test_missing_spec_file_exits_2, test_one_broken_spec_blocks_the_run}` | pass; live smoke #10 shows the absolute path + byte offset in the message |
| Bounded judge waits | `evals/runner.py` (`DEFAULT_JUDGE_TIMEOUT_S`, `future.result(timeout=judge_timeout)`) | `test_eval_runner.py` (judge-timeout cases), `test_eval_judge.py` | pass |
| Cancellation across async/thread boundaries | `evals/runner.py` (`asyncio.to_thread` + `future.cancel()` on expiry, `TimeoutError` surfaced) | `test_eval_runner.py` | pass |
| Teardown of main and judge pipelines | `evals/runner.py::run_spec` | `test_eval_runner.py`; `test_eval_cli.py::test_all_cases_pass_exits_0` asserts the call order `['use','chat','chat','terminate']` | pass |
| CLI-side: connection failure is 2, not 1 | `cli/commands/eval.py` (ported) | `test_eval_cli.py::test_connection_failure_exits_2` | pass; live smoke #11 |

---

## Failure classification

| Observation | Classification |
| --- | --- |
| 21 `ConnectionError` fixture errors in every run | **Pre-existing on develop / environmental** — reproduced identically on the clean develop baseline (70 passed, 21 errors). Engine-bound; requires `./builder client-python:test`, which builds the C++ engine and brackets the suite with a live server. |
| `RocketRideClient_test.py` + `test_cli_integration.py` (57 failures when included) | **Engine-bound: unavailable**, not passes. Includes #1581's `TestCliEval` cases. |
| `ModuleNotFoundError: rocketride_common` from the console script without `PYTHONPATH` | **Pre-existing on develop / environmental** — the source tree is the one layout where `rocketride_common` is not beside `rocketride`; `tests/conftest.py` documents it. Worked around with `PYTHONPATH=packages/client-common/python/src` for the smoke tests only. |
| `PytestConfigWarning: Unknown config option: timeout` before installing `pytest-timeout` | **Pre-existing on develop** — the `timeout` ini option has no plugin in `[dev]` or `[test]`. |
| 3 skips in #1612 without the `otel` extra | **Expected** — resolved by installing `[otel]`; 0 skips after. |
| `builder docs:build` | **Unavailable** — needs a full `pnpm install` plus the engine build chain; `node_modules/` is absent in these worktrees. Substituted: no conflict markers anywhere, section order/heading checks in all four affected doc files, and a repo-wide link-target existence scan (found and fixed the one dead `docs/README-clients.md` link). |
| **Zero** fix-introduced failures | — |

Nothing was weakened: no test deleted, no assertion relaxed, no ruff rule or `noqa` added
beyond the two `# noqa: BLE001` markers that develop itself uses for the same broad-except
pattern in `utils/common.py` and `commands/validate.py`.
