## Summary

- Adds `rocketride otel`, an OpenTelemetry bridge that exports pipeline traces and metrics over OTLP by consuming the engine's **documented** monitor protocol. Zero engine/server changes, zero new base dependencies — everything OTel lives behind `pip install 'rocketride[otel]'`.
- Ships `rocketride.otelbridge` (bridge/config/mapper/setup), the `otel` CLI subcommand, four test modules over a captured real-engine event fixture, and a full user guide with Jaeger, Grafana Tempo, Langfuse and Datadog recipes.
- Privacy by default: no lane payload, prompt, result or error text reaches a span unless `--include-content` is passed (8 KB truncation when it is).

```bash
pip install 'rocketride[otel]'
rocketride otel --endpoint http://collector:4318
```

**Why a client-side bridge.** #498 proposed OTel by instrumenting the server (middleware in `packages/ai`) and was archived in #616 as "promising … not ready for merge". This is the invited refinement with the invasiveness removed: a pure consumer of `rrext_monitor` at `token: "*"`, which `packages/server/docs/observability.md` calls "the recommended scope for an ingestion service". The engine is untouched, so native instrumentation can still land later without conflicting with this.

### What it produces

- **Traces** — `apaevt_flow` becomes a span tree per run: task root → pipe span → component child spans, **paired by component identity**, never by stack position, exactly as the protocol doc warns. `trace.error` → span status `ERROR` + exception event; `apaevt_sse` (`thinking`, `tool_call`, …) → span events; spans still open at `end`/shutdown are closed and flagged `rocketride.span.unclosed=true`.
- **GenAI semantic conventions** — `gen_ai.provider.name` (the deprecated `gen_ai.system` is never emitted), `gen_ai.operation.name` from the well-known list only, `INTERNAL` span kind for in-process component executions. Names follow the July 2026 `semantic-conventions-genai` snapshot and are centralized in one constants block.
- **Metrics** (`--no-metrics` to disable) — `apaevt_status_update` snapshots become OTel instruments: object counts, rates, CPU %, CPU/GPU memory and peaks, on the same endpoint.
- **Operations** — standard OTLP env contract (`--endpoint` > signal-specific `OTEL_EXPORTER_OTLP_*_ENDPOINT` > base `OTEL_EXPORTER_OTLP_ENDPOINT` + signal path), capped-backoff reconnect **with resubscribe** (subscriptions are per-connection, per the doc), SIGINT/SIGTERM → close spans, flush, exit 0. Credential-bearing headers (`Authorization`, `x-api-key`, …) bound for a **non-loopback cleartext** endpoint make the bridge exit 2 before any exporter exists; `--insecure` / `ROCKETRIDE_OTEL_ALLOW_INSECURE=1` is the explicit, stderr-warned opt-out. The startup line prints the endpoint through `redact_endpoint()` (userinfo, query and fragment dropped).
- **Fail-fast packaging** — the base install gains no dependencies, every other subcommand works without the extra, and `rocketride otel` without it exits 2 with the exact install hint before any connection attempt.

## Type

feature (Python SDK + CLI) plus docs. No engine changes, no TypeScript changes, no workflow changes.

## Testing

- [x] Tests added or updated
- [x] Tested locally
- [x] `./builder test` passes — run by CI's Build matrix on `103b3f95` (run [33856598064](https://github.com/rocketride-org/rocketride-server/actions/runs/33856598064), Ubuntu 22.04 / Windows Server 2022 / macOS ARM64 all green; the Ubuntu job's `client-python:run-pytest` step reported 247 passed, 10 skipped). Not run locally, which needs a built engine — the four otel modules were run directly, see below.

Run from `packages/client-python` as `python -m pytest tests/test_otel_bridge.py tests/test_otel_cli.py tests/test_otel_mapper.py tests/test_otel_setup.py -q -o addopts=""`, on Python 3.12, at the current head:

| Environment | Result |
| --- | --- |
| `pip install -e '.[dev,otel]'` — opentelemetry 1.44.0 / semconv 0.65b0 (current PyPI) | **131 passed** |
| same, pinned to opentelemetry 1.42.1 / semconv 0.63b1 (the versions in `nodes/src/nodes/constraints.lock`; CI's engine env installs `opentelemetry-api==1.42.1`) | **131 passed** |
| `pip install -e '.[dev]'` — no opentelemetry at all | **57 passed, 3 skipped** (the `importorskip` modules `test_otel_mapper.py` / `test_otel_setup.py` plus the extra-only gRPC exit-2 test) |

The suite is 131 tests (35 bridge, 23 CLI, 46 mapper, 27 setup); the CodeRabbit round on the rebased head added 32 of them. The `otel` extra's floor is unchanged at `opentelemetry-sdk>=1.27.0` / `opentelemetry-exporter-otlp-proto-http>=1.27.0`; both ends of the range above are verified.

Coverage: the pairing state machine (interleaved pipes, nested same-name components, leave-without-enter, end-before-leaves, restart), run-id promotion and absorption, the per-run pipe cap's LRU eviction, parentage, error mapping, SSE events, a privacy sentinel scan across every exported attribute/event/status, metric deltas, the endpoint/env precedence matrix for both endpoints and headers, endpoint redaction on stdout/stderr, the cleartext-credential refusal and its opt-out, the non-redirecting exporter session, tracer teardown when metric setup fails, signal-handler ownership, reconnect + resubscribe, shutdown flush order, the missing-extra exit path, and a full replay of a captured real-engine event fixture with engine-stamped durations.

Also run on the current head: `ruff check .` and `ruff format --check .` clean repo-wide (ruff 0.16.6, 1753 files), `gitleaks detect --config .gitleaks.toml --log-opts upstream/develop..HEAD` — 13 commits scanned, no leaks.

**Live end-to-end** (from the original July round; **not re-run after the rebase**, so it predates the `body.eventTime` stamping in `68d046e3` and the transport guard in `2a9a50df`): real engine image + `jaegertracing/all-in-one:1.76.0` in Docker, an echo pipeline started with `pipelineTraceLevel='summary'`, bridge on `--endpoint http://127.0.0.1:4318`. After SIGINT, Jaeger's HTTP API returned exactly 1 trace with 6 spans in the contracted hierarchy, `rocketride.*` attributes present, and the message content provably absent from the exported trace. The fixture-replay test (`test_fixture_replay_with_engine_stamps_yields_engine_durations`) is what covers the timestamp change.

## Sync with develop (2026-09-04)

Rebased onto `upstream/develop` @ **65a2e133**. The six original commits replayed with **zero conflicts**; seven commits sit on top, so the branch is 13 commits:

| Commit | Subject |
| --- | --- |
| `6c314fa5` | feat(sdk): rocketride.otelbridge — OpenTelemetry export over the documented ingester protocol (#1609) |
| `118fdabb` | feat(cli): add 'rocketride otel' subcommand + optional [otel] extra (#1609) |
| `d3baf73b` | docs: OpenTelemetry bridge guide with Jaeger, Langfuse, and Datadog recipes |
| `a2eebafa` | fix(sdk): handle partial OpenTelemetry installs — guard the HTTP exporter import |
| `1a4e4e29` | fix(sdk): OTel bridge review round — privacy-gate errors, run-id promotion, header precedence, shutdown ordering |
| `49a2e1e8` | fix(sdk): absorb stranded fallback run state when canonical state precedes it |
| `68d046e3` | fix(sdk): stamp OTel spans with the engine's body.eventTime |
| `1d0f219c` | docs(client-python): publish the OTel bridge guide and mirror its CLI entry |
| `99f3d30b` | docs(changelog): record the rocketride otel bridge under [Unreleased] |
| `196dd053` | docs(client-python): name Grafana Tempo in the OTel backend recipes |
| `2a9a50df` | fix(sdk): address CodeRabbit review round on the rebased head |
| `103b3f95` | test(sdk): skip the loop signal-handler ownership test on Windows |
| `0a5c6f8c` | docs(cli): document the otel --insecure flag in the site CLI reference |

The July review-thread replies say "Fixed in c23b3125" / "Fixed in 7fbf5136"; those are the pre-rebase SHAs of `1a4e4e29` and `49a2e1e8` (identical patch-ids), which are the commits now on the branch.

develop has moved on since the rebase (`65a2e133..0788b9c4`, six commits; `1368d589` / #2040 touches `packages/client-python/pyproject.toml`). `git merge-tree --write-tree upstream/develop HEAD` against `0788b9c4` is clean, so this merges as-is; I will rebase again if you prefer CI to have run on the newer base.

**Re-verified against the post-July protocol changes.** #1661 (run-log continuum) and #1764 (owner-scoped identity) rewired `task_engine.py`/`cmd_monitor.py`. Event bodies still carry `project_id`, `source` and `__id`, which is all the mapper correlates on, and the bridge subscribes by type *name* (`TASK`, `SUMMARY`, `FLOW`, `SSE`) rather than by bitmask, so the new `BILLING`/`DEPLOY` bits and `EVENT_TYPE.ALL == 1023` are transparent to it.

**`body.eventTime` is adopted, not deferred** (`68d046e3`). Since #1661 every forwarded event body carries `eventTime` — epoch seconds, stamped once at ingress — so the guide's old "the wire carries no timestamps, spans use arrival time" limitation was false against the base this merges into. Spans and span events are now stamped with `eventTime`, which makes durations engine-measured rather than bridge-observed. The fallback is exactly the previous behaviour: bodies with no usable stamp, and spans closed outside an event (shutdown, seeded-snapshot reconciliation, tracked-run cap eviction), use the bridge clock. Because a run can therefore mix the two sources, each span records its own start and a close is clamped never to precede it, so no span can report a negative duration. Metric points are still arrival-timed — OTel metric instruments take no explicit timestamp — and that is now stated rather than implied.

**Docs co-location** (`1d0f219c`). Per AGENTS.md the guide belongs under `packages/client-python/docs/`, the tree mounted at `develop/python`; root `docs/` is not in the docs-site glob (`packages/docs/scripts/lib/gather.js:25`), so the 369-line guide was GitHub-only. It moved to `packages/client-python/docs/otel-bridge.md` (site route `/develop/python/otel-bridge`) next to the existing `analytics.md` and `log.md`, its in-repo links became site routes to match its new siblings, and the three references to it were repointed. `packages/client-python/docs/index.md` — the site's Python page, which mirrors the PyPI README's `## CLI` block line for line — gained the `rocketride otel` row and the OpenTelemetry paragraph it was missing.

**Also in this sync:** a `[Unreleased] ### Added` CHANGELOG line (`99f3d30b`), and Grafana Tempo named explicitly in the backend recipes (`196dd053`) since #1609's acceptance list says "Jaeger/Tempo" and the guide only said "Grafana stacks". The guide's Python code blocks are reformatted because ruff formats Markdown code blocks as of 0.16 and CI's `ruff-action` is unpinned — the file would have failed `ruff format --check` at either path.

**CodeRabbit round on the rebased head** (`2a9a50df`, nine threads, each with an in-line reply and resolved): the Langfuse/LangSmith recipes prompt for keys with `read -rs` instead of carrying placeholders, and the Langfuse base64 pipeline strips the 76-column wrap that an 85-character real key pair triggers; the startup line redacts the endpoint; one `validate_transport_security()` guard (in `build_providers` for embedders and again in the CLI for a clean exit 2) refuses credential-looking header names — from `--headers` or any of the three `OTEL_EXPORTER_OTLP_*HEADERS` variables — over a non-loopback cleartext endpoint, with `--insecure` / `ROCKETRIDE_OTEL_ALLOW_INSECURE=1` as the opt-out; the OTLP/HTTP exporters get a session that never follows redirects (`requests` only strips `Authorization` on a host change, so a 3xx replayed `x-api-key`); `OTEL_EXPORTER_OTLP_ENDPOINT` is no longer pre-read into an explicit endpoint that overrode the signal-specific variables; the bridge no longer steals a signal the running loop already handles (`install_signal_handlers=False` for embedders); `MAX_TRACKED_PIPES_PER_RUN` bounds `run.pipes`; and the tracer provider is shut down when metric setup fails. `103b3f95` guards the new signal-ownership test on Windows (ProactorEventLoop has no `add_signal_handler`). `0a5c6f8c` adds the `--insecure` row to the docs-site CLI reference (`packages/docs/content-static/cli.mdx`), which the guide and the argparse help already documented.

**CI on this head** (last CI before the rebase was 2026-07-16): run [33856598064](https://github.com/rocketride-org/rocketride-server/actions/runs/33856598064) on `103b3f95` is green — Ruff, gitleaks, Shell API contract (the `shell:regen-derived` tamper guard from 5e5a2517 and the credentials-catalog `--check` from 210c9c7f), the Build matrix with Postgres/AGE containers and `RR_REQUIRE_DB_TESTS` (8db7a42d) on pnpm 10.33.0, and `check-externals (PR)` with its runtime-libs step (db6c882e; run 33856597605). Helm, container scan and nightly jobs skipped as path-gated. This PR touches no `nodes/**/requirements.txt`, so the node-constraints compile job did not trigger. `0a5c6f8c` (one table row in `cli.mdx`) is on top of that run.

**Not a duplicate of #1541.** #1541 (`feat(alb): saas compatible connection multiplexing and metrics`, Rod-Christensen) adds an engine-side connection-multiplexing and metrics surface under `packages/ai/src/ai/web/metrics/`. Its diff contains zero occurrences of `opentelemetry`, `otlp` or `prometheus`, and it shares **no files** with this PR. The two are the complementary halves of tracking issue #616 — engine-side counters there, protocol-level OTLP export here — and can land in either order.

**Stack note.** This is one of five open PRs of mine that touch the Python CLI or its docs: #1573 (`validate`), #1581 (`eval`), #1586 (chat widget, `docs/README-clients.md`), #1607 (`diff`) and #1613 (the `rrext_store` doc fix). #1573/#1581/#1607 each conflict with this branch on `cli/commands/__init__.py` and `cli/main.py`, and #1613 conflicts on `docs/README-python-client.md` and `packages/client-python/docs/index.md`; whichever lands first, I will rebase the rest and resolve by keeping both imports, both `command_map` entries and both doc lines, bumping the `cli.mdx` parity-note count to the true total. Happy to land them in whatever order you prefer.

**Known follow-up, deliberately not in this PR:** the fallback run key is `f'{project_id}|{source}'`, used only for events that arrive without `__id`. Since #1764 every body also carries `teamId`/`runKind`, so a team's deployed run and a dev run of the same project could alias under that fallback. Folding those fields into the key is a small, separable change I would rather do once a maintainer has signed off on the correlation model.

## Checklist

- [x] Commit messages follow [conventional commits](https://www.conventionalcommits.org/)
- [x] No secrets or credentials included — the captured fixture's auth keys were scrubbed to `pk_EXAMPLEPUBLICKEY…` / `tk_EXAMPLEPRIVATETOKEN…`; gitleaks clean over `develop..HEAD`
- [ ] Wiki updated (if applicable) — n/a
- [ ] Breaking changes documented (if applicable) — none; purely additive

## Linked Issue

Closes #1609 · Refs #616 (the refined successor to the concept archived from #498)

## Notes for reviewers

- FLOW spans require runs started with a `pipelineTraceLevel`; the bridge can only observe, it cannot enable tracing for a run it did not start. `TASK`/`SUMMARY` telemetry flows for every run regardless. Called out in the CLI help and in the guide.
- `--trace-level` is informational only for the same reason. If you would rather not carry a flag that only prints a reminder, say so and I will drop it.
- Jaeger does not ingest OTLP metrics (404 on `/v1/metrics`); the guide says to pair it with `--no-metrics` or point metrics at a collector. Trace export is unaffected.
- What CI actually exercises: the engine env installs `opentelemetry-api==1.42.1` (and, per the skip reason CI printed, a gRPC exporter) but not `opentelemetry-exporter-otlp-proto-http`, so in run 33856598064 the Ubuntu job ran the 104 tests of `test_otel_bridge.py` / `test_otel_cli.py` / `test_otel_mapper.py` (103 passed; `test_real_grpc_protocol_without_exporter_exits_2` skipped because that exporter is present) and skipped `test_otel_setup.py` at import. The 27 setup tests, which construct the real HTTP exporters, are verified locally against 1.42.1 and 1.44.0 (table above). I am happy to add an opt-in job that installs the extra if you want them guaranteed in CI.
- Scope: Python SDK/CLI + docs only. No engine changes, no new base dependencies, no workflow changes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

#Hire-Me-RocketRide

## Sync with develop (2026-09-10)

- `1d16eed5` merges `upstream/develop` @ `f9a25cbb` into the branch (merge commit; the approved head `0a5c6f8c` is its first parent, no history rewritten). Develop rewrote the Python CLI (`RocketRideCLI`/`BaseCommand` → `setup_parser()`/`_dispatch()` with `async run_<cmd>(args)` handlers) and merged #1573's `validate`, so `otel` is ported to `async run_otel(args, client=None)` with behavior held fixed: the `otelbridge` package (config, bridge, mapper, exporters) is byte-identical to the approved head; the missing-extra guard still runs before any client exists; endpoint precedence, transport-security/plaintext-credential refusal, run/pipe caps and bounded queues, signal-handler preservation and shutdown/flush re-verified with their tests, plus a live smoke of the credential-header refusal and endpoint redaction.
- Shared helper: `_add_connection_args(parser, *, json_arg=True)` — the byte-identical hunk #1581 carries, so whichever lands second auto-merges; `otel` passes `json_arg=False` because it produces no JSON envelope. Inherited change to note: `--uri` now defaults to `http://localhost:5565` (develop's convention) instead of `https://api.rocketride.ai`; `ROCKETRIDE_URI` / `--uri` behave as before.
- Tests: two tests that asserted on the deleted `RocketRideCLI` token machinery are removed and five dispatch-level tests added (their coverage — `otel` needs no token — is kept by `test_dispatch_routes_bare_otel_without_requiring_a_token`); 134 in this PR's files, 204 in the offline package run (develop's 70 + 134), ruff clean, wheel ships `otelbridge` and the `otel` extra.
- Docs follow develop's restructure: `docs/README-clients.md` was moved to `docs/develop/README-clients.md`, so this PR's sentence is re-applied there, and `packages/client-python/docs/otel-bridge.md`'s "See also" link (which pointed at the deleted path) is re-based.
- CI: [run 34488937607](https://github.com/rocketride-org/rocketride-server/actions/runs/34488937607) on `1d16eed5` — `CI OK` green: 16 checks passed, 4 expected skips (Build on Ubuntu 22.04 / Windows Server 2022 / macOS ARM64, Ruff, gitleaks, Shell API contract, check-externals). Not verifiable outside CI: a real OTLP collector round-trip and live SIGINT.
- Lands last of the three (#1607 → #1581 → #1612). The two product questions are unchanged and remain for maintainers: whether to carry a fourth CLI subcommand, and whether a client-side `rrext_monitor` bridge is the direction for #616.
