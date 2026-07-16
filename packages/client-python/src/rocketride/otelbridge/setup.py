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
OpenTelemetry provider construction for the RocketRide OTel bridge.

This module builds the TracerProvider / MeterProvider pair (with OTLP
exporters) that the ``rocketride otel`` bridge feeds. ALL imports of the
``opentelemetry`` packages are lazy (function-local): importing this module
never requires the 'otel' extra, and a missing extra surfaces as
:class:`OtelNotInstalledError` with the exact install command.

Endpoint semantics (matching the OTLP exporter spec):
    - ``config.endpoint`` set: treated as a BASE url; the per-signal paths
      ``/v1/traces`` / ``/v1/metrics`` are appended unless already present,
      so pasting Langfuse's ``https://<host>/api/public/otel`` or LangSmith's
      ``https://api.smith.langchain.com/otel`` just works (http protocol).
    - ``config.endpoint`` unset: the exporters are constructed without an
      explicit endpoint so the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` /
      ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_HEADERS``
      environment variables (and the localhost:4318 default) apply.
    - ``protocol='grpc'``: requires the optional
      ``opentelemetry-exporter-otlp-proto-grpc`` package (not part of the
      'otel' extra); gRPC endpoints are used verbatim (no per-signal path).
"""

from typing import Any, Callable, Dict, Optional, Tuple

_INSTALL_HINT = "pip install 'rocketride[otel]'"
_GRPC_INSTALL_HINT = 'pip install opentelemetry-exporter-otlp-proto-grpc'

# Instrumentation scope name for tracer/meter lookups.
SCOPE_NAME = 'rocketride.otelbridge'


class OtelNotInstalledError(RuntimeError):
    """Raised when an OpenTelemetry dependency needed by the bridge is missing."""


def missing_otel_message() -> str:
    """Return the user-facing message for a missing 'otel' extra."""
    return f"The 'rocketride otel' bridge requires the OpenTelemetry SDK. Install it with: {_INSTALL_HINT}"


def _resolve_endpoint(base: str, signal_path: str) -> str:
    """
    Append a per-signal OTLP path to a base endpoint unless already present.

    Args:
        base: User-supplied base URL (e.g. ``http://localhost:4318`` or
            ``https://cloud.langfuse.com/api/public/otel``).
        signal_path: Signal path without leading slash (``v1/traces``).
    """
    trimmed = base.rstrip('/')
    if trimmed.endswith('/' + signal_path):
        return trimmed
    return f'{trimmed}/{signal_path}'


def _build_resource(config: Any) -> Any:
    """Build the OTel Resource carrying service.name (+ service.version when known)."""
    from opentelemetry.sdk.resources import Resource

    attributes: Dict[str, Any] = {'service.name': config.service_name}
    try:
        from importlib.metadata import version

        attributes['service.version'] = version('rocketride')
    except Exception:  # noqa: BLE001 - version is best-effort metadata only
        pass
    return Resource.create(attributes)


def _exporter_headers(config: Any) -> Optional[Dict[str, str]]:
    """Return explicit headers, or None so OTEL_EXPORTER_OTLP_HEADERS applies."""
    headers = getattr(config, 'headers', None)
    return dict(headers) if headers else None


def _build_span_exporter(config: Any) -> Any:
    """Build the OTLP span exporter for config.protocol ('http' or 'grpc')."""
    protocol = getattr(config, 'protocol', 'http') or 'http'
    headers = _exporter_headers(config)
    if protocol == 'grpc':
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        except ImportError as exc:
            raise OtelNotInstalledError(
                f'--protocol grpc requires the OTLP gRPC exporter. Install it with: {_GRPC_INSTALL_HINT}'
            ) from exc
        if config.endpoint:
            return OTLPSpanExporter(endpoint=config.endpoint, headers=headers)
        return OTLPSpanExporter(headers=headers)

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    if config.endpoint:
        return OTLPSpanExporter(endpoint=_resolve_endpoint(config.endpoint, 'v1/traces'), headers=headers)
    return OTLPSpanExporter(headers=headers)


def _build_metric_exporter(config: Any) -> Any:
    """Build the OTLP metric exporter for config.protocol ('http' or 'grpc')."""
    protocol = getattr(config, 'protocol', 'http') or 'http'
    headers = _exporter_headers(config)
    if protocol == 'grpc':
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        except ImportError as exc:
            raise OtelNotInstalledError(
                f'--protocol grpc requires the OTLP gRPC exporter. Install it with: {_GRPC_INSTALL_HINT}'
            ) from exc
        if config.endpoint:
            return OTLPMetricExporter(endpoint=config.endpoint, headers=headers)
        return OTLPMetricExporter(headers=headers)

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    if config.endpoint:
        return OTLPMetricExporter(endpoint=_resolve_endpoint(config.endpoint, 'v1/metrics'), headers=headers)
    return OTLPMetricExporter(headers=headers)


def build_providers(config: Any) -> Tuple[Any, Any, Callable[[], None]]:
    """
    Build (tracer, meter, shutdown_fn) from an OtelConfig.

    The providers are kept local (the global OpenTelemetry tracer/meter
    providers are never touched) so tests and embedders stay isolated.
    ``shutdown_fn`` flushes and shuts down both providers; call it once on
    exit (SIGINT/SIGTERM handling lives in the bridge loop).

    Args:
        config: An object with ``endpoint``, ``protocol``, ``service_name``,
            ``include_content``, ``no_metrics`` and ``headers`` attributes
            (see ``rocketride.otelbridge.config.OtelConfig``).

    Raises:
        OtelNotInstalledError: The 'otel' extra (or the gRPC exporter for
            ``protocol='grpc'``) is not installed.
    """
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise OtelNotInstalledError(missing_otel_message()) from exc

    resource = _build_resource(config)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(_build_span_exporter(config)))
    tracer = tracer_provider.get_tracer(SCOPE_NAME)

    if getattr(config, 'no_metrics', False):
        meter_provider = MeterProvider(resource=resource, metric_readers=[])
    else:
        reader = PeriodicExportingMetricReader(_build_metric_exporter(config))
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    meter = meter_provider.get_meter(SCOPE_NAME)

    def shutdown() -> None:
        """Flush pending telemetry and shut down both providers."""
        tracer_provider.shutdown()
        meter_provider.shutdown()

    return tracer, meter, shutdown
