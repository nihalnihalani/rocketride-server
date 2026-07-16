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
Unit tests for rocketride.otelbridge.setup (provider/exporter construction).

Covers OTLP endpoint semantics (base URL + per-signal path appending, env var
fallbacks), header pass-through, provider construction, the lazy-import
guarantee (module import never requires the 'otel' extra, verified in a
subprocess with opentelemetry blocked), and the gRPC-extra error path.
Skipped gracefully when the optional 'otel' extra is absent.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pytest

pytest.importorskip('opentelemetry')
pytest.importorskip('opentelemetry.sdk')

from rocketride.otelbridge.setup import (
    OtelNotInstalledError,
    _build_metric_exporter,
    _build_span_exporter,
    _resolve_endpoint,
    build_providers,
    missing_otel_message,
)

SRC_DIR = Path(__file__).parent.parent / 'src'

try:
    import opentelemetry.exporter.otlp.proto.grpc  # noqa: F401

    HAS_GRPC_EXPORTER = True
except ImportError:
    HAS_GRPC_EXPORTER = False


@dataclass
class BridgeConfigStub:
    """Minimal stand-in matching the OtelConfig attribute surface."""

    endpoint: Optional[str] = None
    protocol: str = 'http'
    service_name: str = 'rocketride-engine'
    include_content: bool = False
    no_metrics: bool = False
    headers: Dict[str, str] = field(default_factory=dict)


# =========================================================================
# ENDPOINT SEMANTICS
# =========================================================================


def test_resolve_endpoint_appends_signal_path():
    assert _resolve_endpoint('http://localhost:4318', 'v1/traces') == 'http://localhost:4318/v1/traces'


def test_resolve_endpoint_tolerates_trailing_slash():
    assert _resolve_endpoint('http://localhost:4318/', 'v1/traces') == 'http://localhost:4318/v1/traces'


def test_resolve_endpoint_keeps_full_signal_path_verbatim():
    full = 'http://localhost:4318/v1/traces'
    assert _resolve_endpoint(full, 'v1/traces') == full


def test_resolve_endpoint_supports_vendor_base_paths():
    """Langfuse/LangSmith users paste base ingest URLs; the signal path is appended."""
    assert (
        _resolve_endpoint('https://cloud.langfuse.com/api/public/otel', 'v1/traces')
        == 'https://cloud.langfuse.com/api/public/otel/v1/traces'
    )
    assert (
        _resolve_endpoint('https://api.smith.langchain.com/otel', 'v1/traces')
        == 'https://api.smith.langchain.com/otel/v1/traces'
    )


def test_span_exporter_uses_config_endpoint_and_headers():
    config = BridgeConfigStub(endpoint='http://collector:4318', headers={'x-api-key': 'k1'})
    exporter = _build_span_exporter(config)
    assert exporter._endpoint == 'http://collector:4318/v1/traces'
    assert dict(exporter._headers)['x-api-key'] == 'k1'


def test_metric_exporter_uses_config_endpoint():
    config = BridgeConfigStub(endpoint='http://collector:4318')
    exporter = _build_metric_exporter(config)
    assert exporter._endpoint == 'http://collector:4318/v1/metrics'


def test_env_endpoint_honored_when_config_endpoint_absent(monkeypatch):
    """OTEL_EXPORTER_OTLP_ENDPOINT is a base URL; the exporter appends the signal path."""
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://envhost:4318')
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', raising=False)
    exporter = _build_span_exporter(BridgeConfigStub(endpoint=None))
    assert exporter._endpoint == 'http://envhost:4318/v1/traces'


def test_signal_specific_env_endpoint_honored_when_config_endpoint_absent(monkeypatch):
    """The standard signal-specific env var is used verbatim by the SDK exporter."""
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT', raising=False)
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', 'http://traces.example:4318/v1/traces')
    exporter = _build_span_exporter(BridgeConfigStub(endpoint=None))
    assert exporter._endpoint == 'http://traces.example:4318/v1/traces'


def test_env_headers_honored_when_config_headers_absent(monkeypatch):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS', 'x-api-key=abc123')
    exporter = _build_span_exporter(BridgeConfigStub(endpoint='http://collector:4318'))
    assert dict(exporter._headers).get('x-api-key') == 'abc123'


# =========================================================================
# PROVIDER CONSTRUCTION
# =========================================================================


def test_build_providers_returns_usable_tracer_meter_shutdown():
    config = BridgeConfigStub(endpoint='http://localhost:4318', no_metrics=True)
    tracer, meter, shutdown = build_providers(config)
    assert callable(shutdown)
    assert hasattr(tracer, 'start_span')
    # The meter must accept the instruments MetricsMapper creates.
    meter.create_up_down_counter('test.updown', unit='{object}')
    meter.create_gauge('test.gauge', unit='%')
    # no_metrics=True and no ended spans: shutdown flushes nothing and returns.
    shutdown()


def test_build_providers_sets_service_name_resource():
    config = BridgeConfigStub(endpoint='http://localhost:4318', service_name='my-bridge', no_metrics=True)
    tracer, _meter, shutdown = build_providers(config)
    resource = tracer.resource  # SDK tracer exposes its provider resource
    assert resource.attributes['service.name'] == 'my-bridge'
    shutdown()


def test_build_providers_with_metrics_wires_a_periodic_reader(monkeypatch):
    """With no_metrics=False a periodic reader exports recorded measurements at shutdown."""
    import io

    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

    import rocketride.otelbridge.setup as setup_module

    buffer = io.StringIO()
    monkeypatch.setattr(setup_module, '_build_metric_exporter', lambda config: ConsoleMetricExporter(out=buffer))
    config = BridgeConfigStub(endpoint='http://localhost:4318', no_metrics=False)
    _tracer, meter, shutdown = build_providers(config)
    counter = meter.create_up_down_counter('test.counter', unit='{object}')
    counter.add(1, {'k': 'v'})
    shutdown()
    assert 'test.counter' in buffer.getvalue()


# =========================================================================
# MISSING-DEPENDENCY PATHS
# =========================================================================


def test_missing_otel_message_names_the_extra():
    assert "pip install 'rocketride[otel]'" in missing_otel_message()


@pytest.mark.skipif(HAS_GRPC_EXPORTER, reason='OTLP gRPC exporter is installed')
def test_grpc_protocol_without_grpc_exporter_raises_install_hint():
    config = BridgeConfigStub(endpoint='http://localhost:4317', protocol='grpc')
    with pytest.raises(OtelNotInstalledError, match='grpc'):
        _build_span_exporter(config)
    with pytest.raises(OtelNotInstalledError, match='grpc'):
        _build_metric_exporter(config)


_IMPORT_SAFETY_SCRIPT = """
import sys
from importlib.abc import MetaPathFinder


class _Blocker(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'opentelemetry' or fullname.startswith('opentelemetry.'):
            raise ImportError('opentelemetry blocked for import-safety test')
        return None


sys.meta_path.insert(0, _Blocker())
for name in list(sys.modules):
    if name.startswith('opentelemetry'):
        del sys.modules[name]

import rocketride.otelbridge  # must import without the 'otel' extra
from rocketride.otelbridge.mapper import FlowSpanMapper
from rocketride.otelbridge.setup import OtelNotInstalledError, build_providers


class Cfg:
    endpoint = None
    protocol = 'http'
    service_name = 's'
    include_content = False
    no_metrics = True
    headers = {}


try:
    build_providers(Cfg())
except OtelNotInstalledError as exc:
    assert "rocketride[otel]" in str(exc), str(exc)
else:
    raise SystemExit('build_providers did not raise OtelNotInstalledError')

try:
    FlowSpanMapper(None)
except OtelNotInstalledError:
    pass
else:
    raise SystemExit('FlowSpanMapper did not raise OtelNotInstalledError')

print('IMPORT_SAFE_OK')
"""


def test_module_import_is_safe_without_otel_extra():
    """The otelbridge package must import (and fail helpfully) without the extra."""
    env = dict(os.environ)
    env['PYTHONPATH'] = str(SRC_DIR)
    result = subprocess.run(
        [sys.executable, '-c', _IMPORT_SAFETY_SCRIPT],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, f'stdout={result.stdout!r} stderr={result.stderr!r}'
    assert 'IMPORT_SAFE_OK' in result.stdout
