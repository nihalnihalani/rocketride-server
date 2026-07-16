# MIT License
#
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
RocketRide CLI OpenTelemetry Bridge Command Implementation.

This module provides the OtelCommand class for exporting live pipeline traces
and metrics to any OpenTelemetry collector over OTLP through the RocketRide
CLI. Use this command to observe pipeline executions in backends such as
Jaeger, Grafana Tempo, Datadog, Langfuse, or LangSmith without any engine or
server changes: the bridge is a pure consumer of the engine's documented
WebSocket monitor protocol.

The command subscribes to the TASK, SUMMARY, FLOW, and SSE monitor event
types with the wildcard token scope and maps them to OTel spans (pipeline
flow) and metrics (task status snapshots), exporting both over the same OTLP
endpoint.

Trace level: the bridge can only observe runs; it cannot change the trace
level of a run it did not start. Pipeline FLOW spans appear only for runs
started with the ``pipelineTraceLevel`` execute argument, e.g.
``client.use(pipelineTraceLevel='summary')``. Without it, the bridge still
exports task lifecycle spans and status metrics.

Key Features:
    - OTLP export of pipeline flow spans and task status metrics
    - Wildcard monitor subscription covering all tasks for the API key
    - Standard OTEL_EXPORTER_OTLP_ENDPOINT/_HEADERS/OTEL_SERVICE_NAME support
      (with no endpoint configured at all, the exporters' own env semantics
      apply, including OTEL_EXPORTER_OTLP_TRACES/METRICS_ENDPOINT)
    - Privacy by default: payload content excluded unless --include-content
    - Automatic reconnection with capped exponential backoff
    - Graceful shutdown on SIGINT/SIGTERM (spans closed, exporters flushed)

Usage:
    rocketride otel --apikey <key>
    rocketride otel --endpoint http://localhost:4318 --service-name my-engine
    rocketride otel --headers 'Authorization=Basic <b64>' --no-metrics
    rocketride otel --include-content --apikey <key>

Requires the optional OpenTelemetry dependencies:
    pip install 'rocketride[otel]'

Components:
    OtelCommand: Main command implementation for the OpenTelemetry bridge
"""

import importlib.util
import sys
from typing import TYPE_CHECKING

from .base import BaseCommand
from ...otelbridge.bridge import run_bridge
from ...otelbridge.config import OtelConfig

# Safe without the 'otel' extra: setup.py keeps all opentelemetry imports lazy.
from ...otelbridge.setup import OtelNotInstalledError

if TYPE_CHECKING:
    from ..main import RocketRideClient

# Exact install hint for the missing-extra error path (contract: exit code 2)
OTEL_INSTALL_HINT = "pip install 'rocketride[otel]'"


def _otel_available() -> bool:
    """
    Check whether the optional OpenTelemetry SDK is installed.

    Probes for the ``opentelemetry`` and ``opentelemetry.sdk`` modules
    without importing them, so the check itself never pays import cost and
    never fails on a partially installed distribution.

    Returns:
        bool: True when the 'rocketride[otel]' extra appears importable.
    """
    try:
        return (
            importlib.util.find_spec('opentelemetry') is not None
            and importlib.util.find_spec('opentelemetry.sdk') is not None
        )
    except (ImportError, ValueError):
        return False


class OtelCommand(BaseCommand):
    """
    Command implementation for the OpenTelemetry bridge.

    Exports live pipeline traces and metrics over OTLP by consuming the
    engine's WebSocket monitor protocol. Runs until interrupted (Ctrl+C or
    SIGTERM), closing open spans and flushing exporters on shutdown.

    Example:
        ```python
        # Initialize and execute the OTel bridge
        command = OtelCommand(cli, args)
        exit_code = await command.execute(client)
        ```

    Key Features:
        - Lazy dependency guard: clear exit code 2 with install hint when
          the 'rocketride[otel]' extra is missing (checked before connecting)
        - Configuration precedence: CLI args > OTEL_* env vars > defaults
        - Traces and metrics over one OTLP endpoint (http/protobuf default)
        - Content privacy gate via --include-content
    """

    def __init__(self, cli, args):
        """
        Initialize OtelCommand with CLI context and parsed arguments.

        Args:
            cli: CLI instance providing cancellation state and event handling
            args: Parsed command line arguments containing exporter options
                  and connection configuration
        """
        super().__init__(cli, args)

    async def execute(self, client: 'RocketRideClient') -> int:
        """
        Execute the OpenTelemetry bridge command.

        Verifies the optional OpenTelemetry dependencies are installed,
        resolves the exporter configuration, and runs the bridge loop until
        interrupted.

        Args:
            client: RocketRideClient instance for server communication
                (connected by the bridge if not already connected)

        Returns:
            Exit code: 0 for graceful shutdown, 1 for unexpected errors,
            2 when dependencies are missing or the startup connection fails

        Process Flow:
            1. Guard: missing 'rocketride[otel]' extra -> exit 2 with hint
               (before any connection attempt)
            2. Resolve OtelConfig (CLI args > OTEL_* env vars > defaults)
            3. Print the effective bridge configuration
            4. Run the bridge loop (connect, subscribe, dispatch, reconnect)
            5. Graceful shutdown on SIGINT/SIGTERM: spans closed, exporters
               flushed, exit 0
        """
        # Dependency guard MUST run before any connection attempt
        if not _otel_available():
            print(
                f"Error: 'rocketride otel' requires the OpenTelemetry extra. Install it with: {OTEL_INSTALL_HINT}",
                file=sys.stderr,
            )
            return 2

        # Resolve configuration: CLI args > OTEL_* env vars > defaults
        config = OtelConfig.from_args_env(self.args)

        # --trace-level is documentation-surface only: the monitor protocol
        # has no way to change the trace level of runs the bridge didn't start
        trace_level = getattr(self.args, 'trace_level', None)
        if trace_level:
            print(
                f'Note: --trace-level={trace_level} is informational only. The bridge cannot change the '
                f'trace level of runs it did not start; start runs with '
                f"pipelineTraceLevel='{trace_level}' (e.g. client.use(pipelineTraceLevel='{trace_level}')) "
                f'to emit FLOW events at that level.'
            )

        # Show the effective configuration before entering the run loop.
        # With no endpoint configured the OTLP exporters resolve their own:
        # OTEL_EXPORTER_OTLP_TRACES/METRICS_ENDPOINT, else the SDK default.
        if config.endpoint:
            endpoint_display = config.endpoint
        else:
            sdk_default = 'localhost:4317' if config.protocol == 'grpc' else 'http://localhost:4318'
            endpoint_display = f'exporter default (OTEL_EXPORTER_OTLP_*_ENDPOINT or {sdk_default})'
        print(f'OpenTelemetry bridge starting (endpoint: {endpoint_display}, protocol: {config.protocol})')
        print(f'  service.name: {config.service_name}')
        print(f'  metrics: {"disabled" if config.no_metrics else "enabled"}')
        print(f'  payload content: {"included (size-capped)" if config.include_content else "excluded"}')
        print(
            "  FLOW spans require runs started with pipelineTraceLevel (e.g. client.use(pipelineTraceLevel='summary'))"
        )

        try:
            # Run the bridge until stopped (returns 0) or startup fails (2)
            return await run_bridge(client, config)

        except (ImportError, OtelNotInstalledError) as e:
            # Missing optional dependency surfaced after the guard, e.g.
            # --protocol grpc without the OTLP gRPC exporter package
            # (build_providers raises OtelNotInstalledError for that path).
            print(f'Error: {e}', file=sys.stderr)
            return 2

        except KeyboardInterrupt:
            # Fallback when signal handlers could not be installed
            print('\nStopping OpenTelemetry bridge...')
            return 0

        except Exception as e:
            print(f'Error: OpenTelemetry bridge failed: {e}', file=sys.stderr)
            return 1
