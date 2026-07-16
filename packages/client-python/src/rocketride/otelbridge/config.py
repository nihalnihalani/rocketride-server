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
Configuration for the RocketRide OpenTelemetry bridge.

This module provides the OtelConfig dataclass consumed by the bridge run loop
(``rocketride.otelbridge.bridge``) and the OTLP provider setup
(``rocketride.otelbridge.setup``). Configuration is resolved with the
precedence: explicit CLI arguments > standard ``OTEL_*`` environment
variables > built-in defaults.

Environment variables honored when the matching CLI argument is absent:
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP base URL (signal paths such as
      ``/v1/traces`` are appended by the exporter setup, matching the
      OpenTelemetry SDK's base-endpoint semantics)
    - OTEL_EXPORTER_OTLP_HEADERS: comma-separated ``key=value`` pairs sent
      with every OTLP export request (e.g. ``Authorization=Basic <b64>`` for
      Langfuse or ``x-api-key=<key>,Langsmith-Project=<proj>`` for LangSmith)
    - OTEL_SERVICE_NAME: the ``service.name`` resource attribute

When neither ``--endpoint`` nor ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, the
resolved ``endpoint`` stays ``None`` and the OTLP exporters are constructed
bare, so the SDK's own environment semantics apply: the signal-specific
``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``
variables are honored, falling back to the SDK defaults
(``http://localhost:4318`` for http/protobuf, ``localhost:4317`` for gRPC).
An explicit ``--endpoint`` or ``OTEL_EXPORTER_OTLP_ENDPOINT`` overrides the
signal-specific variables (CLI-arg-over-env precedence, documented here
because the OTLP spec orders the two env vars the other way around).

This module intentionally imports nothing from ``opentelemetry`` so it is
importable without the ``rocketride[otel]`` extra installed.

Components:
    OtelConfig: Bridge configuration dataclass with from_args_env resolution
    parse_headers: Parser for comma-separated ``key=value`` header strings
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

# Built-in defaults (OTLP over HTTP/protobuf; endpoint defaults are the
# OTLP exporters' own, so signal-specific OTEL_EXPORTER_OTLP_*_ENDPOINT
# environment variables stay effective when no endpoint is given here)
DEFAULT_PROTOCOL = 'http'
DEFAULT_SERVICE_NAME = 'rocketride-engine'

# Standard OpenTelemetry environment variable names
ENV_OTLP_ENDPOINT = 'OTEL_EXPORTER_OTLP_ENDPOINT'
ENV_OTLP_HEADERS = 'OTEL_EXPORTER_OTLP_HEADERS'
ENV_SERVICE_NAME = 'OTEL_SERVICE_NAME'


def parse_headers(headers_str: Optional[str]) -> Dict[str, str]:
    """
    Parse a comma-separated ``key=value`` header string into a dict.

    Follows the OTEL_EXPORTER_OTLP_HEADERS wire format: pairs are separated
    by commas and each pair is split on the FIRST ``=`` only, so values that
    themselves contain ``=`` (e.g. base64 padding in
    ``Authorization=Basic cGs6c2s=``) survive intact. Whitespace around keys
    and values is stripped; empty pairs and pairs without ``=`` are skipped.
    Values are passed through verbatim (no URL decoding).

    Args:
        headers_str: Raw header string, e.g. ``'a=1,x-api-key=abc'``.
            None or empty returns an empty dict.

    Returns:
        Dict[str, str]: Parsed header name/value pairs.
    """
    headers: Dict[str, str] = {}
    if not headers_str:
        return headers

    for pair in headers_str.split(','):
        pair = pair.strip()
        if not pair or '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        key = key.strip()
        if key:
            headers[key] = value.strip()

    return headers


@dataclass
class OtelConfig:
    """
    Configuration for the OpenTelemetry bridge.

    Attributes:
        endpoint: OTLP endpoint base URL, or None to defer to the OTLP
            exporters' own environment/default semantics (including the
            signal-specific ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` /
            ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`` variables). When set,
            signal paths (``/v1/traces``, ``/v1/metrics``) are appended by
            the exporter setup.
        protocol: OTLP transport, ``'http'`` (http/protobuf, default) or
            ``'grpc'`` (requires the optional grpc exporter package).
        service_name: Value for the ``service.name`` resource attribute.
        include_content: When True, pipeline payload content (trace data,
            lane payloads, results) is included in span attributes/events,
            subject to the mapper's size cap. Default False: no payload
            content reaches any span.
        no_metrics: When True, only traces are exported; apaevt_status_update
            snapshots are not mapped to OTel metrics.
        headers: Extra headers sent with every OTLP export request.
    """

    endpoint: Optional[str] = None
    protocol: str = DEFAULT_PROTOCOL
    service_name: str = DEFAULT_SERVICE_NAME
    include_content: bool = False
    no_metrics: bool = False
    headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_args_env(cls, args: Any, env: Optional[Mapping[str, str]] = None) -> 'OtelConfig':
        """
        Build an OtelConfig from parsed CLI arguments and the environment.

        Resolution precedence for each field: CLI argument (when present and
        non-empty) > standard ``OTEL_*`` environment variable > default.
        Missing attributes on ``args`` are treated as absent, so partial
        namespaces (e.g. in tests) work.

        Args:
            args: Parsed argparse namespace (or any object with optional
                ``endpoint``, ``protocol``, ``service_name``, ``headers``,
                ``include_content`` and ``no_metrics`` attributes).
            env: Environment mapping override; defaults to ``os.environ``.

        Returns:
            OtelConfig: Fully resolved bridge configuration.
        """
        environ: Mapping[str, str] = os.environ if env is None else env

        # None (not a hardcoded default) when unset, so the SDK exporters'
        # env semantics — incl. OTEL_EXPORTER_OTLP_TRACES/METRICS_ENDPOINT —
        # and their protocol-appropriate defaults stay in effect.
        endpoint = getattr(args, 'endpoint', None) or environ.get(ENV_OTLP_ENDPOINT) or None
        protocol = getattr(args, 'protocol', None) or DEFAULT_PROTOCOL
        service_name = getattr(args, 'service_name', None) or environ.get(ENV_SERVICE_NAME) or DEFAULT_SERVICE_NAME

        headers_arg = getattr(args, 'headers', None)
        headers = parse_headers(headers_arg if headers_arg else environ.get(ENV_OTLP_HEADERS))

        return cls(
            endpoint=endpoint,
            protocol=protocol,
            service_name=service_name,
            include_content=bool(getattr(args, 'include_content', False)),
            no_metrics=bool(getattr(args, 'no_metrics', False)),
            headers=headers,
        )
