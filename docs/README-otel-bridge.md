# OpenTelemetry Bridge (`rocketride otel`)

The OpenTelemetry bridge exports **live pipeline traces and metrics** from a running
RocketRide engine to any OpenTelemetry collector over OTLP — Jaeger, Grafana, Datadog,
Langfuse, LangSmith, or anything else that ingests OTLP. It ships with the Python client
as the `rocketride otel` CLI command and requires **zero engine or server changes**: the
bridge is a pure consumer of the engine's documented
[WebSocket monitor protocol](../packages/server/docs/observability.md), subscribing to the
`TASK`, `SUMMARY`, `FLOW`, and `SSE` event streams with the wildcard token scope (the
documented scope for an ingestion service) and translating them into OTel spans and
metrics on the fly. Point it at your engine and your collector, and every pipeline run
visible to your API key shows up as a trace.

```text
RocketRide engine ──(WebSocket monitor events)──▶ rocketride otel ──(OTLP)──▶ your backend
```

- [Install](#install)
- [Quickstart: Jaeger end-to-end](#quickstart-jaeger-end-to-end)
- [CLI reference](#cli-reference)
- [Backend recipes](#backend-recipes)
- [The span model](#the-span-model)
- [Attributes](#attributes)
- [Privacy: content is excluded by default](#privacy-content-is-excluded-by-default)
- [Metrics](#metrics)
- [Reconnection and shutdown](#reconnection-and-shutdown)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

---

## Install

The bridge's OpenTelemetry dependencies are an optional extra — the base `rocketride`
package gains no new dependencies:

```bash
pip install 'rocketride[otel]'
```

Running `rocketride otel` without the extra exits with code 2 and prints the install
command above.

## Quickstart: Jaeger end-to-end

Run Jaeger all-in-one (UI + OTLP receivers, in-memory storage):

```bash
docker run --rm -d --name jaeger \
  -p 16686:16686 -p 4317:4317 -p 4318:4318 \
  jaegertracing/all-in-one:1.76.0
```

Start the bridge — the defaults already point at `http://localhost:4318` (OTLP over
HTTP/protobuf):

```bash
export ROCKETRIDE_URI=ws://localhost:5565   # or wss://api.rocketride.ai + ROCKETRIDE_APIKEY
rocketride otel
```

Now start a pipeline run **with a trace level** so it emits `FLOW` events (see
[the callout below](#flow-spans-need-a-trace-level) — this is the step everyone misses):

```python
import asyncio
from rocketride import RocketRideClient

async def main():
    # Uses ROCKETRIDE_URI / ROCKETRIDE_APIKEY from the environment
    async with RocketRideClient() as client:
        result = await client.use(filepath='pipeline.pipe', pipelineTraceLevel='summary')
        token = result['token']
        await client.send(token, 'hello traces', objinfo={'name': 'input.txt'}, mimetype='text/plain')
        await client.terminate(token)

asyncio.run(main())
```

Open [http://localhost:16686](http://localhost:16686), select the **rocketride-engine**
service, and click **Find Traces**. You'll see one trace per run: a task root span, a pipe
span per object, and component child spans underneath.

## CLI reference

```bash
rocketride otel [--endpoint URL] [--protocol http|grpc] [--service-name NAME]
                [--headers k=v,k=v] [--include-content] [--no-metrics]
                [--trace-level none|metadata|summary|full]
```

| Flag                | Default                                       | Description                                                                                                                            |
| ------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `--endpoint <url>`  | `OTEL_EXPORTER_OTLP_ENDPOINT`, else the exporter default (`http://localhost:4318` for http, `localhost:4317` for grpc) | OTLP **base** URL. The signal paths `/v1/traces` / `/v1/metrics` are appended automatically unless already present, so pasting Langfuse's or LangSmith's ingest URL just works. With neither the flag nor `OTEL_EXPORTER_OTLP_ENDPOINT` set, the signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` variables are honored too. |
| `--protocol <p>`    | `http`                                        | OTLP transport: `http` (http/protobuf) or `grpc`. The gRPC exporter is **not** part of the `otel` extra — see [Troubleshooting](#troubleshooting). |
| `--service-name <n>`| `OTEL_SERVICE_NAME` or `rocketride-engine`    | The `service.name` resource attribute your backend groups by.                                                                          |
| `--headers <pairs>` | `OTEL_EXPORTER_OTLP_HEADERS`                  | Comma-separated `key=value` pairs sent with every OTLP request. Values are split on the *first* `=` only, so base64 padding survives. **Prefer the env var for secrets** — command-line arguments are visible in shell history and `ps` output; keep `--headers` for non-secret headers. Without the flag, the OTel SDK resolves `OTEL_EXPORTER_OTLP_HEADERS` and the signal-specific `OTEL_EXPORTER_OTLP_TRACES_HEADERS` / `OTEL_EXPORTER_OTLP_METRICS_HEADERS` itself. |
| `--include-content` | off                                           | Include pipeline payload content in spans, truncated to 8 KB per attribute. **By default no payload text reaches any span.**            |
| `--no-metrics`      | off                                           | Export traces only; task status snapshots are not mapped to metrics.                                                                   |
| `--trace-level <l>` | —                                             | **Informational only.** The bridge cannot change the trace level of runs it did not start; this flag just prints a reminder of how to start traced runs. |

Plus the standard connection arguments shared by all subcommands: `--uri`
(`ROCKETRIDE_URI`) and `--apikey` (`ROCKETRIDE_APIKEY`). No task token is needed — the
bridge subscribes to every task your API key owns.

**Configuration precedence:** explicit CLI flags > standard `OTEL_*` environment
variables (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`,
`OTEL_SERVICE_NAME`) > built-in defaults. Header environment variables are
resolved by the OTel SDK exporters themselves (never pre-parsed by the bridge),
so the signal-specific `OTEL_EXPORTER_OTLP_TRACES_HEADERS` /
`OTEL_EXPORTER_OTLP_METRICS_HEADERS` keep their spec-defined precedence over the
generic variable whenever `--headers` is not given.

**Exit codes:** `0` graceful shutdown (Ctrl+C / SIGTERM), `1` unexpected runtime error,
`2` missing dependency (the `otel` extra, or the gRPC exporter with `--protocol grpc`)
or startup connection/subscribe failure.

### FLOW spans need a trace level

`apaevt_flow` events — and therefore per-component spans — fire **only for runs started
with a `pipelineTraceLevel`** (an argument of the `execute` request, i.e.
`client.use(..., pipelineTraceLevel='summary')`). The bridge can only observe; it cannot
turn tracing on for a run it did not start. Without a trace level you still get task
lifecycle spans and all metrics, just no component breakdown. `summary` is the practical
level: lane writes and final results without per-call noise.

## Backend recipes

### Jaeger / any OTLP collector

Covered by the [quickstart](#quickstart-jaeger-end-to-end): OTLP/HTTP on port 4318
(or `--protocol grpc` against 4317 with the gRPC exporter installed). The same shape works
for the OpenTelemetry Collector, Grafana stacks, and any other standard OTLP receiver.

### Langfuse

Langfuse ingests OTLP **traces over HTTP only** (no gRPC, no metrics) at
`/api/public/otel`, with HTTP Basic auth built from your project keys:

```bash
# Build the Basic auth value from your Langfuse project keys (pk-lf-... : sk-lf-...)
export LANGFUSE_AUTH=$(echo -n 'pk-lf-your-public-key:sk-lf-your-secret-key' | base64)
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${LANGFUSE_AUTH}"

rocketride otel \
  --endpoint https://cloud.langfuse.com/api/public/otel \
  --no-metrics
```

The auth header travels via `OTEL_EXPORTER_OTLP_HEADERS` rather than a `--headers`
argument so the secret never lands in your shell history or shows up in `ps` output.

Use `https://us.cloud.langfuse.com/api/public/otel` for the US region, or
`https://<your-host>/api/public/otel` for self-hosted (Langfuse v3.22.0+). Pass
`--no-metrics`: Langfuse's OTLP ingest is traces-only. Spans from LLM components carry
`gen_ai.*` attributes, which Langfuse maps into its own data model.

### LangSmith

LangSmith ingests OTLP traces over HTTP at `/otel`, authenticated with an `x-api-key`
header (optional `Langsmith-Project` header to pick the project):

```bash
# Env var, not --headers: keeps the API key out of shell history / ps output
export OTEL_EXPORTER_OTLP_HEADERS='x-api-key=your-langsmith-api-key,Langsmith-Project=your-project-name'

rocketride otel \
  --endpoint https://api.smith.langchain.com/otel \
  --no-metrics
```

Regional hosts: `eu.api.smith.langchain.com` (EU); self-hosted follows
`https://<your-domain>/api/v1/otel`.

### Datadog

Send OTLP to a Datadog Agent (or an OpenTelemetry Collector with the Datadog exporter)
that has OTLP ingestion enabled — the agent handles the Datadog API key, so the bridge
needs no auth headers:

```bash
rocketride otel --endpoint http://localhost:4318
```

Datadog natively maps `gen_ai.*` semantic-convention attributes (semconv v1.37+) in its
LLM Observability product, so LLM component spans light up without a Datadog SDK.

## The span model

One trace per pipeline run. The hierarchy the bridge builds:

```text
task <task name>                     task root span (INTERNAL), one per run
│                                      opened on apaevt_task begin (or the seeded
│                                      "running" snapshot when attaching mid-run)
│
└── <object name>                    pipe root span, one per (run, pipe id) segment
    │                                  opened on flow op=begin, closed on op=end;
    │                                  named after the object flowing through
    │
    ├── chat                         component span (llm_openai_1)
    │   │                              SpanKind CLIENT, gen_ai.operation.name=chat,
    │   │                              gen_ai.provider.name=openai
    │   └─ ● thinking                apaevt_sse events attach as span events to the
    │                                  innermost open span of their pipe
    │
    └── response_1                   plain component span (INTERNAL)
                                       opened on op=enter, closed on op=leave —
                                       paired by component identity, one span per
                                       lane write (including control lanes)
```

Runs are correlated primarily on the wire correlation id (`__id`,
`<token-prefix>.<source>`), falling back to `(project_id, source)`. A run first
observed through events lacking `__id` is promoted to its canonical id when that id
later arrives — never tracked twice. Details worth knowing:

- **enter/leave pairing is by component identity**, never stack position (the monitor
  protocol documents why). Expect one short component span per lane write — including
  the `open`/`closing`/`close` control lanes.
- **Component spans still open at run end or bridge shutdown** are closed with status
  `UNSET` and `rocketride.span.unclosed=true` — an honest "we never saw the leave", not
  an error.
- **Attaching mid-run:** events for pipes the bridge never saw begin get an implicit
  root span marked `rocketride.span.implicit=true`.
- **Errors:** a `trace.error` on a component `leave` event sets span status `ERROR`,
  records an `exception` span event, and sets `error.type` (`_OTHER` — the wire error
  is a free-form string). The error *text* is treated as payload: by default the
  status description is a generic `component error` and the exception event carries
  no message; with `--include-content` the wire error text is exported (8 KB cap).
- **Task restarts** close the current spans and open a fresh task span with
  `rocketride.task.restarted=true`.
- **GenAI conventions:** component ids map to GenAI semantic conventions where the id
  makes the role unambiguous — `llm_*` → `chat` (CLIENT), `embedding_*` → `embeddings`
  (CLIENT), `agent_*` → `invoke_agent` (INTERNAL), `tool_*` → `execute_tool` (INTERNAL,
  with `gen_ai.tool.name`). `gen_ai.provider.name` is set only for providers on the
  semconv well-known list (e.g. `llm_openai_*` → `openai`, `llm_anthropic_*` →
  `anthropic`); unknown providers omit the attribute rather than inventing a value.

## Attributes

| Attribute                        | On                    | Meaning                                                             |
| -------------------------------- | --------------------- | ------------------------------------------------------------------- |
| `rocketride.project_id`          | all spans and metrics | Pipeline project id                                                 |
| `rocketride.source`              | all spans and metrics | Pipeline source (e.g. `webhook_1`)                                  |
| `rocketride.run_id`              | all spans             | Wire correlation id of the run (`<token-prefix>.<source>`)          |
| `rocketride.task.name`           | task spans            | Task name from the lifecycle event                                  |
| `rocketride.task.restarted`      | task spans            | `true` when this span was opened by a task restart                  |
| `rocketride.pipe_id`             | pipe/component spans  | Pipe index within the pipeline                                      |
| `rocketride.object`              | pipe spans            | Name of the object flowing through this segment                     |
| `rocketride.component`           | component spans       | Component id (e.g. `llm_openai_1`)                                  |
| `rocketride.lane`                | component spans       | Lane being written (e.g. `text`, `open`, `close`)                   |
| `rocketride.flow.result`         | component spans       | Flow result string on leave (e.g. `continue`)                       |
| `rocketride.span.unclosed`       | any span              | `true`: closed at run end/shutdown without a matching leave         |
| `rocketride.span.implicit`       | pipe spans            | `true`: created for a pipe whose begin the bridge never saw         |
| `rocketride.flow.unmatched_leaves` | pipe spans          | Count of leave events that matched no open component span           |
| `rocketride.sse.type`            | span events           | SSE message type (e.g. `thinking`, `tool_call`)                     |
| `gen_ai.operation.name`          | LLM/agent/tool spans  | `chat`, `embeddings`, `invoke_agent`, or `execute_tool`             |
| `gen_ai.provider.name`           | LLM/embedding spans   | Well-known provider value derived from the component id             |
| `gen_ai.tool.name`               | tool spans            | Tool name derived from the component id                             |
| `error.type`                     | failed spans          | Always `_OTHER` (wire errors are free-form strings)                 |
| `rocketride.trace.data` / `rocketride.result` / `rocketride.sse.data` | content-gated | Payload content — **only with `--include-content`**, 8 KB cap |

`gen_ai.*` names follow the July 2026 snapshot of the
`open-telemetry/semantic-conventions-genai` registry (Development stability, no tagged
release); deprecated names such as `gen_ai.system` or `gen_ai.usage.prompt_tokens` are
never emitted.

## Privacy: content is excluded by default

By default **no pipeline payload content reaches any span** — not lane data
(`trace.data`), not run-segment results, not SSE message bodies, and not the
free-form error text of failed components (node errors routinely quote their input;
the error *signal* — `ERROR` status, `error.type`, the `exception` span event — still
exports, with the generic description `component error`). Only structural metadata
(names, ids, lanes, counts, timings) is exported, so the bridge is safe to point at a
shared collector out of the box.

Opting in with `--include-content` copies payload content into the
`rocketride.trace.data`, `rocketride.result`, and `rocketride.sse.data` attributes and
exports the verbatim wire error text in span statuses and `exception` events —
JSON-serialized and truncated to **8192 characters** per attribute. Treat the flag as
what it is: pipeline inputs and outputs flowing into your telemetry backend.

## Metrics

Unless `--no-metrics` is set, every `apaevt_status_update` snapshot (roughly every 500 ms
per running task) is mapped to OTel metrics, exported over the same OTLP endpoint. All
instruments carry `rocketride.project_id` / `rocketride.source` attributes.

| Instrument                       | Type            | Unit         | Meaning                                  |
| -------------------------------- | --------------- | ------------ | ---------------------------------------- |
| `rocketride.objects.total`       | up-down counter | `{object}`   | Objects seen by the pipeline run         |
| `rocketride.objects.completed`   | up-down counter | `{object}`   | Objects completed                        |
| `rocketride.objects.failed`      | up-down counter | `{object}`   | Objects failed                           |
| `rocketride.rate.count`          | gauge           | `{object}/s` | Instantaneous object processing rate     |
| `rocketride.rate.size`           | gauge           | `By/s`       | Instantaneous byte processing rate       |
| `rocketride.cpu.percent`         | gauge           | `%`          | Engine CPU utilization                   |
| `rocketride.cpu.percent.peak`    | gauge           | `%`          | Peak engine CPU utilization              |
| `rocketride.memory.cpu_mb`       | gauge           | `MBy`        | Engine CPU memory usage                  |
| `rocketride.memory.cpu_mb.peak`  | gauge           | `MBy`        | Peak engine CPU memory usage             |
| `rocketride.memory.gpu_mb`       | gauge           | `MBy`        | Engine GPU memory usage                  |
| `rocketride.memory.gpu_mb.peak`  | gauge           | `MBy`        | Peak engine GPU memory usage             |

Object counters are fed **per-run deltas** between snapshots, so re-sent snapshots don't
double-count; a task restart resets the engine's counts, which legitimately produces
negative deltas. The snapshot's `tokens.*` block is **compute credits (billing), not LLM
tokens**, and is deliberately not exported as `gen_ai.usage.*`.

## Reconnection and shutdown

- **Reconnects** use capped exponential backoff (1 s doubling up to 30 s). Monitor
  subscriptions are per-connection and not durable, but the SDK replays them on every
  reconnect, and the re-seeded "running"/status snapshots are handled idempotently —
  already-open spans are not duplicated. The seeded snapshot is also authoritative:
  tracked runs it no longer announces (their `end` was missed while disconnected) are
  closed with `rocketride.span.unclosed=true` and dropped.
- **Ctrl+C / SIGTERM** closes all open spans (marked `rocketride.span.unclosed=true`),
  flushes both exporters, and exits `0`.
- **Startup failure** (engine unreachable, subscribe rejected) prints a clean message to
  stderr and exits `2` so supervisors can tell "never started" from "was stopped".

## Troubleshooting

| Symptom                                                        | Cause / fix                                                                                                                                     |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Exits immediately with code 2 and an install hint               | The `otel` extra is missing: `pip install 'rocketride[otel]'`.                                                                                   |
| Bridge runs, tasks appear, but **no component spans**           | The run was not started with a trace level. Start runs with `client.use(..., pipelineTraceLevel='summary')` — the bridge cannot enable it for you. |
| Exits with code 2, "connection" in the message                  | Engine unreachable at startup: check `--uri` / `ROCKETRIDE_URI` and `--apikey` / `ROCKETRIDE_APIKEY`.                                            |
| Bridge runs but nothing arrives in the backend                  | Exporter can't reach the collector (exports fail in the background; the bridge keeps running). Check host/port — OTLP/HTTP is **4318**, gRPC is **4317** — and that `--protocol` matches the receiver. |
| `--protocol grpc` fails with an install error                   | The gRPC exporter is not part of the extra: `pip install opentelemetry-exporter-otlp-proto-grpc`. Note Langfuse does not accept gRPC at all.     |
| Langfuse/LangSmith receive traces but metric exports error      | Their OTLP ingest is traces-only — run with `--no-metrics`.                                                                                      |
| Spans named `chat` carry no model name or token counts          | Expected — see [Limitations](#limitations).                                                                                                      |

## Limitations

Honest edges of a protocol-level bridge:

- **Timestamps are arrival time.** The monitor wire protocol carries no event
  timestamps, so span start/end use the bridge's clock at event arrival. Durations are
  bridge-observed (WebSocket latency included), not engine-measured.
- **LLM token usage and model names appear only when nodes surface them in events.**
  Flow events at `summary` level carry neither, so `gen_ai.request.model` and
  `gen_ai.usage.*` are honestly omitted rather than guessed, and LLM span names degrade
  to the bare operation (`chat`, not `chat gpt-4.1`). The status snapshot's `tokens.*`
  are compute credits, not LLM tokens, and are never mapped to `gen_ai.usage.*`.
- **`gen_ai.*` conventions are Development stability.** Attribute names follow the July
  2026 snapshot of `open-telemetry/semantic-conventions-genai`; they are centralized in
  one constants module and may be revised as the spec evolves.
- **Trace level is the run starter's choice.** `--trace-level` on the bridge is
  informational only; there is no protocol surface to change it for running tasks.
- **Restart accounting.** Object up-down counters are per-run deltas, so a task restart
  (counts reset) produces a negative step by design.
- **Spans export when they close.** The batch span processor exports a span only at
  `end()`, so a run whose `end` event is never observed holds its spans back until the
  bridge closes them — at the next reconnect's seeded snapshot (runs no longer
  announced are closed), when the tracked-run cap (1024) evicts the
  least-recently-eventful run, or at shutdown. Such spans are flagged
  `rocketride.span.unclosed=true`. There is deliberately no idle timeout: a quiet but
  alive task (e.g. a webhook service) keeps being announced and is never expired by a
  clock. Metric delta bookkeeping is likewise capped (4096 runs, least recently
  updated evicted first), so a bridge left running for weeks has bounded memory.

## See also

- [Monitor protocol reference](../packages/server/docs/observability.md) — the event
  stream the bridge consumes
- [Python client](README-python-client.md) — SDK and the rest of the CLI
- [Client libraries overview](README-clients.md)
