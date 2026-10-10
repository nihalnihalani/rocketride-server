# #1612 — description wording edits for dsapandora's note (round 4); apply after the round-4 commit is pushed and green

## Line 3 (verbatim today)
- Adds `rocketride otel`, an OpenTelemetry bridge that exports pipeline traces and metrics over OTLP by consuming the engine's **documented** monitor protocol. Zero engine/server changes, zero new base dependencies — everything OTel lives behind `pip install 'rocketride[otel]'`.

## Line 3 (replacement — draft)
- Adds `rocketride otel`, an OpenTelemetry bridge that exports pipeline traces and metrics over OTLP by consuming the engine's **documented** monitor protocol. No engine/server code changes and no new runtime dependencies — everything OTel lives behind `pip install 'rocketride[otel]'`; in CI the OpenTelemetry SDK and OTLP/HTTP exporter are installed only for the client-python test step, so the engine's own build harness does not carry them.

## Line 107 (verbatim today)
- Scope: Python SDK/CLI + docs only. No engine changes, no new base dependencies, no workflow changes.

## Line 107 (replacement — draft)
- Scope: Python SDK/CLI + docs, plus the client-python test task installing its own OpenTelemetry test dependencies. No engine code changes, no new runtime dependencies, no workflow changes.

## Round-4 sync bullet (appended to the sync section; placeholders {HEAD} {CI})
- **Round 4 `{HEAD}` (2026-09-11):** dsapandora approved with one note: the OTel test dependencies had been declared in the engine's build harness (`packages/server/build-requirements.txt`), so every engine build carried them and the "zero new base dependencies" line overstated the change. They are now installed only for the client-python test step ({MECHANISM}); `packages/server/build-requirements.txt` is back to its develop state; the test-module docstrings and docs point at the new location; the two description claims above are reworded. CI: {CI}, with the run log showing the install in the client-python test step and the otel modules still collected and passing.

## Summary-comment follow-up paragraph (appended; placeholders)
**Follow-up ({HEAD}):** dsapandora's note is addressed — the OpenTelemetry test dependencies moved out of the engine's build harness into a client-python-scoped install that runs only before the client-python pytest step ({MECHANISM}); `packages/server/build-requirements.txt` is back to develop's content, and the description no longer claims "zero new base dependencies". CI: {CI}.
