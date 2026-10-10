# PR #1612 — `rocketride otel` (OpenTelemetry bridge) — develop-sync candidate

| | |
| --- | --- |
| Branch (in my worktree) | `pr1612-develop-sync` |
| Candidate SHA | `1d16eed5f0af20c4669b84f288b47bac51dbc322` |
| Parents | `0a5c6f8ce9937a77eaf1d29f17801b1901e6a06e` (PR head) · `f9a25cbbd73f8feb9fbc99ea3aeb5bd241dafc1e` (develop) |
| Worktree | `/Users/nihalnihalani/Desktop/Github/rocketride-server/.claude/worktrees/agent-a3f470621685a0c1d/wt/pr1612` |
| Push line for the lead | `git push origin 1d16eed5f0af20c4669b84f288b47bac51dbc322:refs/heads/feat/RR-1609-otel-bridge` |
| Descendant of the current remote head? | yes |
| Superseded | `8edb7df31…` (amended to fix a dead doc link found by the integration check) |

## What changed relative to the approved head

### Files carried over unchanged (proved byte-identical)

`git diff refs/review-pr/1612 -- packages/client-python/src/rocketride/otelbridge packages/client-python/tests/test_otel_bridge.py packages/client-python/tests/test_otel_mapper.py packages/client-python/tests/test_otel_setup.py packages/client-python/tests/fixtures` → **empty**.

That is the entire bridge (`bridge.py`, `config.py`, `mapper.py`, `setup.py`, `__init__.py`),
the 654-line event fixture, and three of the four test files — so every accepted fix that
lives below the CLI is the approved code verbatim.

### Files changed by the merge

| File | Change |
| --- | --- |
| `docs/README-clients.md` | **Deleted** — accepting develop's deletion. develop moved the file to `docs/develop/README-clients.md`. |
| `docs/develop/README-clients.md` | The PR's OpenTelemetry sentence re-applied at the same anchor paragraph ("Each document lists every constructor option…"), with the link re-based one level deeper: `../../packages/client-python/docs/otel-bridge.md` (verified to resolve). |
| `packages/client-python/docs/otel-bridge.md` | **One line**: the "See also" link `blob/develop/docs/README-clients.md` → `blob/develop/docs/develop/README-clients.md`. It pointed at the file develop deleted. Found by the integration check's link scan. |
| `packages/client-python/src/rocketride/cli/commands/otel.py` | Ported `class OtelCommand(BaseCommand)` → `async def run_otel(args, client=None)`. `_endpoint_display` became a module function; `_otel_available` is unchanged. **Ordering is load-bearing** and is preserved: the missing-extra guard runs first, then config resolution, then `validate_transport_security`, then the banner — and only then is a client built. The old CLI created (but did not connect) the client before `execute(client)`; `run_otel` builds an **unconnected** client itself via `_make_client(args)`, because `run_bridge` owns connecting and reconnecting. A client `run_otel` creates it closes; an injected one it never touches. **Not** wired to `run_cli_command`, whose catch-all maps every error to 1 and would erase the 1-vs-2 distinction. |
| `packages/client-python/src/rocketride/cli/main.py` | Develop's `setup_parser()`/`_dispatch()` taken whole; `otel` re-registered after `validate` with the PR's exact arguments and help plus an exit-code `epilog`; one docstring line; one `_dispatch` branch; one local import. **Plus** `_add_connection_args(parser, *, json_arg: bool = True)` — `otel` needs `--uri`/`--apikey` but emits no JSON result, so it must not advertise a `--json` it ignores. Written byte-identically to #1581's version so the two merges auto-resolve. |
| `packages/client-python/src/rocketride/cli/commands/__init__.py` | `from .otel import run_otel` + `'run_otel'` in `__all__`, alphabetically placed. |
| `packages/client-python/tests/test_otel_cli.py` | Retargeted at `run_otel(args, client)`, `cli_main.setup_parser()`, `cli_main._dispatch()`. **Added 3**, **replaced 2** — see below. |
| `packages/client-python/pyproject.toml` | Auto-merged; the `otel` extra intact. |
| `CHANGELOG.md`, `docs/README-python-client.md`, `packages/client-python/docs/index.md`, `packages/docs/content-static/cli.mdx` | Both this PR's and develop's entries/sections kept, `validate` first. |

### Test changes that need a reviewer's eye

`TestCliRouting` had two tests written against the pre-rewrite CLI:

- `test_run_routes_otel_without_requiring_token` — replaced by
  `test_dispatch_routes_bare_otel_without_requiring_a_token`, which parses bare
  `rocketride otel`, asserts `not hasattr(args, 'token')`, and drives the real `_dispatch`.
- `test_events_still_requires_token_but_otel_does_not` — **removed**. It asserted on
  `rocketride events ALL`, and develop deleted the `events` command outright, so the test
  could only have been kept by asserting behavior that no longer exists. The property it
  guarded (that `otel` is not snagged by another command's token requirement) is what the
  replacement above checks.

Two tests were added in their place, so coverage went **up**, not down:

- `test_cli_client_is_built_from_args_and_left_unconnected` — patches
  `rocketride.RocketRideClient`, drives `_dispatch`, and asserts the client is constructed
  from `--uri`/`--apikey`, handed to the bridge with `connect_calls == 0`, and disconnected
  afterwards.
- `test_injected_client_is_not_disconnected_by_the_command` — a caller-supplied client stays
  the caller's.

Plus two registration tests (`test_otel_is_registered_exactly_once_alongside_validate`,
`test_otel_has_no_shared_json_option_but_validate_does`).

Net diff over develop: **20 files** — the PR's own 20, with `docs/README-clients.md` traded
for `docs/develop/README-clients.md`. No other develop content dropped.

## Accepted-fix survival

| Accepted fix | Survives? | Evidence in code | Regression test | Live check |
| --- | --- | --- | --- | --- |
| OTLP generic vs signal-specific endpoint precedence | yes | `otelbridge/config.py::{effective_endpoint, OtelConfig.from_args_env}` — unchanged | `test_otel_bridge.py::TestOtelConfig::{test_defaults_when_no_args_no_env, test_signal_specific_env_left_to_the_sdk_exporters, test_env_used_when_args_absent, test_generic_endpoint_env_left_to_the_sdk_exporters, test_explicit_endpoint_arg_still_wins, test_args_override_env, test_header_env_vars_left_to_the_sdk_exporters, test_header_value_keeps_base64_padding, test_header_parsing_edge_cases}` | banner shows `exporter default (http://localhost:4318)` when nothing is set, and the explicit `--endpoint` when given |
| Transport-security validation (plaintext-credential guard) | yes | `otelbridge/config.py::validate_transport_security` + `run_otel` calling it **before** the banner and before any client exists | `test_otel_bridge.py::TestTransportSecurity` (11), `test_otel_cli.py::TestOtelTransportSecurity` (5, incl. `test_cleartext_credentials_refused_with_exit_2` which asserts the bridge was never called) | `otel --endpoint http://collector.example:4318 --headers 'x-api-key=SUPERSECRET'` → exit 2; stderr names the header **key**, `SUPERSECRET` appears nowhere; `--insecure` flips it to a warning; `http://localhost:4318` is allowed |
| Finite resource limits (run/pipe caps, bounded queues, eviction) | yes | `otelbridge/mapper.py` — unchanged | `test_otel_mapper.py::{test_tracked_run_cap_evicts_least_recently_eventful_run, test_tracked_pipe_cap_evicts_least_recently_eventful_pipe, test_tracked_pipe_cap_bounds_a_never_ending_run, test_metrics_last_counts_bounded_lru, test_include_content_truncates_to_cap, test_error_leave_with_content_truncates_string_errors_to_cap}` (46 in the file, all pass) | — (needs a live event stream) |
| Preservation of existing event-loop signal handlers | yes | `otelbridge/bridge.py::_loop_owns_signal` inspects `loop._signal_handlers` and **skips** registration when the loop already owns SIGINT/SIGTERM (because `add_signal_handler` replaces rather than chains); previous `signal.getsignal` values are restored in the `finally` — unchanged | `test_otel_bridge.py::{test_pre_existing_loop_signal_handler_is_not_stolen, test_install_signal_handlers_false_registers_nothing}` | — |
| Shutdown / flush | yes | `otelbridge/bridge.py` closes spans then flushes exporters, removes its handlers, restores the previous event handler — unchanged | `test_otel_bridge.py::{test_shutdown_closes_spans_before_flushing_exporters, test_chains_and_restores_previous_event_handler, test_startup_connect_failure_returns_2, test_subscription_failure_returns_2, test_reconnects_with_backoff_without_resubscribing, test_mapper_exception_is_logged_not_fatal}` | unreachable `--uri` → exit **2** with `otel-bridge: unable to connect to RocketRide server: …` |
| Endpoint redaction on stdout | yes | `run_otel` calls `_endpoint_display` → `redact_endpoint`, never the raw endpoint | `test_otel_cli.py::{test_startup_line_redacts_endpoint_credentials, test_startup_line_redacts_env_endpoint}` | `--endpoint 'https://svcuser:sup3rs3cret@collector.example:4318/v1/traces?sig=DEADBEEF'` → banner shows `https://collector.example:4318/v1/traces?<redacted>`; none of `svcuser`, `sup3rs3cret`, `DEADBEEF` appear on stdout or stderr |
| Missing-extra guard before any connection | yes | first statement in `run_otel`; the client is not even constructed until after it | `test_otel_cli.py::TestMissingExtraGuard::test_exits_2_with_hint_before_connecting` (asserts `client.connect_calls == 0`), `::test_missing_dependency_from_bridge_exits_2` (both `OtelNotInstalledError` and raw `ImportError`) | — (the extra is installed in this env) |
| `--trace-level` is informational only | yes | unchanged text, both the `none` and the level-named branches | `test_otel_cli.py::{test_trace_level_prints_informational_note, test_trace_level_none_says_tracing_stays_disabled}` | `--trace-level summary` prints the note including `pipelineTraceLevel='summary'` |

## Test tally

| Scope | Result |
| --- | --- |
| PR's own files (with the `otel` extra) | 134 passed (`test_otel_cli` 26 · `test_otel_bridge` 35 · `test_otel_mapper` 46 · `test_otel_setup` 27) |
| Same without the extra | 60 passed, 3 skipped (mapper/setup import `opentelemetry`) |
| `packages/client-python` offline suite | 204 passed, 21 engine-bound errors (= 70 develop baseline + 134) |
| `ruff check` / `ruff format --check` | clean / 98 files formatted |
| Wheel + sdist | built; `otelbridge` package and `cli/commands/otel.py` present; METADATA declares `Provides-Extra: dev, otel, test` with both OTLP requirements under `extra == "otel"`; console script present |

## Not verifiable here

- `test_cli_integration.py` and `RocketRideClient_test.py` — engine-bound; need
  `./builder client-python:test`. Unavailable, not passing.
- A real OTLP collector round-trip (spans/metrics actually landing in Jaeger/Tempo/Langfuse)
  and real SIGINT/SIGTERM handling of a long-running bridge — both need a live engine plus a
  collector. The unit tests cover the logic; the end-to-end path is untested here.
- `--protocol grpc` against a real exporter: `opentelemetry-exporter-otlp-proto-grpc` is not
  in the `otel` extra, so `test_real_grpc_protocol_without_exporter_exits_2` skipped
  (`requires the 'otel' extra` guard) — that is the PR's own intended skip condition.
- `builder docs:build`.
