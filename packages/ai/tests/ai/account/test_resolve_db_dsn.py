# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""Tests for ``AccountBase.resolve_db_dsn`` — the env-gated DB broker call.

The broker contract (locked 2026-07-23, shipped as saas #381):
``POST {RR_DB_BROKER_URL} {"tenant_id": ...}`` with a Bearer token ->
``{"database", "role", "dsn", "created"}`` (only ``dsn`` is read), idempotent.
A real localhost HTTP server plays the broker so the actual urllib code path
is exercised.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ai.account.base import AccountBase

TEST_DSN = 'postgresql://r_t1_ab:secret@pooler.internal:5432/t_t1_ab?sslmode=require'
TEST_TOKEN = 'broker-token-123'


class _Minimal(AccountBase):
    async def authenticate(self, credential):  # pragma: no cover - unused
        return None


class _FakeBroker(BaseHTTPRequestHandler):
    """Stands in for the data-core provisioner."""

    requests: list = []

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length) or b'{}')
        type(self).requests.append({'auth': self.headers.get('Authorization'), 'body': body})

        tenant = body.get('tenant_id', '')
        if self.headers.get('Authorization') != f'Bearer {TEST_TOKEN}':
            self.send_response(401)
            self.end_headers()
            return
        if tenant == 'unknown-tenant':
            self.send_response(404)
            self.end_headers()
            return
        if tenant == 'no-dsn-tenant':
            payload = {'database': 't_broken', 'role': 't_broken_rw', 'created': False}
        elif tenant == 'no-sslmode-tenant':
            bare = 'postgresql://r_t1_ab:secret@pooler.internal:5432/t_t1_ab'
            payload = {'database': 't_t1_ab', 'role': 't_t1_ab_rw', 'dsn': bare, 'created': False}
        elif tenant == 'bad-scheme-tenant':
            payload = {'database': 't_t1_ab', 'role': 't_t1_ab_rw', 'dsn': 'mysql://u:p@h/db', 'created': False}
        else:
            payload = {'database': 't_t1_ab', 'role': 't_t1_ab_rw', 'dsn': TEST_DSN, 'created': False}
        raw = json.dumps(payload).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # silence request logging
        pass


@pytest.fixture()
def broker(monkeypatch):
    _FakeBroker.requests = []
    server = HTTPServer(('127.0.0.1', 0), _FakeBroker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/provision'
    monkeypatch.setenv('RR_DB_BROKER_URL', url)
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', TEST_TOKEN)
    yield _FakeBroker
    server.shutdown()
    server.server_close()


def _resolve(client_id: str) -> str:
    return asyncio.run(_Minimal().resolve_db_dsn(client_id))


def test_unconfigured_env_raises_signin_error(monkeypatch):
    monkeypatch.delenv('RR_DB_BROKER_URL', raising=False)
    monkeypatch.delenv('RR_DB_BROKER_TOKEN', raising=False)
    with pytest.raises(NotImplementedError, match='require signing into RocketRide cloud'):
        _resolve('tenant-1')


def test_partial_env_still_raises(monkeypatch, broker):
    monkeypatch.delenv('RR_DB_BROKER_TOKEN', raising=False)
    with pytest.raises(NotImplementedError):
        _resolve('tenant-1')


def test_resolves_dsn_via_broker(broker):
    assert _resolve('tenant-1') == TEST_DSN


def test_client_id_passed_verbatim_as_tenant_id_with_bearer(broker):
    _resolve('Client-42 ')
    assert broker.requests == [{'auth': f'Bearer {TEST_TOKEN}', 'body': {'tenant_id': 'Client-42'}}]


def test_idempotent_recall_returns_same_dsn(broker):
    assert _resolve('tenant-1') == _resolve('tenant-1') == TEST_DSN
    assert len(broker.requests) == 2


def test_broker_4xx_raises_runtime_error(broker):
    with pytest.raises(RuntimeError, match=r'^DB broker rejected provisioning for this organization \(HTTP 404\)$'):
        _resolve('unknown-tenant')


def test_bad_token_is_reported_as_server_configuration_not_the_account(broker, monkeypatch):
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', 'wrong')
    with pytest.raises(RuntimeError) as err:
        _resolve('tenant-1')
    message = str(err.value)
    assert message.startswith("DB broker refused this server's credentials (HTTP 401)")
    assert 'operator' in message and 'organization' not in message
    assert 'wrong' not in message and TEST_TOKEN not in message


def _http_error(code):
    return urllib.error.HTTPError('https://broker.example/provision', code, 'x', hdrs=None, fp=io.BytesIO(b'body'))


@pytest.mark.parametrize(
    'code,expected',
    [
        (401, "DB broker refused this server's credentials (HTTP 401)"),
        (403, "DB broker refused this server's credentials (HTTP 403)"),
        (400, 'DB broker rejected provisioning for this organization (HTTP 400)'),
        (404, 'DB broker rejected provisioning for this organization (HTTP 404)'),
        (500, 'DB broker unavailable (HTTP 500)'),
        (503, 'DB broker unavailable (HTTP 503)'),
    ],
)
def test_broker_http_errors_are_classified(monkeypatch, code, expected):
    def raise_http_error(*_args, **_kwargs):
        raise _http_error(code)

    monkeypatch.setattr(urllib.request, 'urlopen', raise_http_error)
    with pytest.raises(RuntimeError) as err:
        AccountBase._call_db_broker('https://broker.example/provision', TEST_TOKEN, 'tenant-1')
    assert str(err.value).startswith(expected)


def test_broker_http_error_response_is_closed(monkeypatch):
    response_body = io.BytesIO(b'broker error')
    error = urllib.error.HTTPError(
        'https://broker.example/provision',
        503,
        'Service Unavailable',
        hdrs=None,
        fp=response_body,
    )

    def raise_http_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(urllib.request, 'urlopen', raise_http_error)

    with pytest.raises(RuntimeError, match='unavailable.*503'):
        AccountBase._call_db_broker('https://broker.example/provision', TEST_TOKEN, 'tenant-1')

    assert response_body.closed


def test_missing_dsn_in_response_raises(broker):
    with pytest.raises(RuntimeError, match='did not include a DSN'):
        _resolve('no-dsn-tenant')


def test_unreachable_broker_raises(monkeypatch):
    monkeypatch.setenv('RR_DB_BROKER_URL', 'http://127.0.0.1:9/provision')
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', TEST_TOKEN)
    with pytest.raises(RuntimeError) as err:
        _resolve('tenant-1')
    assert str(err.value) == 'DB broker unreachable (connection refused)'


@pytest.mark.parametrize(
    'raised,expected',
    [
        (urllib.error.URLError(ConnectionRefusedError(61, 'Connection refused')), 'connection refused'),
        (urllib.error.URLError(TimeoutError('timed out')), 'timed out'),
        (TimeoutError('timed out'), 'timed out'),
        (urllib.error.URLError(OSError(8, 'nodename nor servname provided')), 'network error'),
        (ValueError('unknown url type: https://user:secret@broker.example'), 'network error'),
    ],
)
def test_unreachable_broker_never_echoes_the_error_text(monkeypatch, raised, expected):
    def fail(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError) as err:
        AccountBase._call_db_broker('https://user:secret@broker.example/provision', TEST_TOKEN, 'tenant-1')
    assert str(err.value) == f'DB broker unreachable ({expected})'


@pytest.mark.parametrize('body', [b'<html>502 Bad Gateway</html>', b'\xff\xfe not utf-8', b''])
def test_broker_reply_that_is_not_json_is_an_invalid_response_not_a_network_error(monkeypatch, body):
    """A proxy or broker answering 200 with a non-JSON body reached us: say so, not "unreachable"."""
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *_args, **_kwargs: io.BytesIO(body))
    with pytest.raises(RuntimeError) as err:
        AccountBase._call_db_broker('https://broker.example/provision', TEST_TOKEN, 'tenant-1')
    assert str(err.value) == 'DB broker returned an invalid response (not JSON)'


def test_empty_client_id_rejected(broker):
    with pytest.raises(ValueError, match='non-empty client_id'):
        _resolve('   ')


# ---------------------------------------------------------------------------
# Transport security guards
# ---------------------------------------------------------------------------


def test_http_broker_url_rejected_for_non_localhost(monkeypatch):
    """The broker token is a credential — never send it over plain http to a
    remote host (a deployment typo must fail loudly).
    """
    monkeypatch.setenv('RR_DB_BROKER_URL', 'http://broker.internal/provision')
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', TEST_TOKEN)
    with pytest.raises(RuntimeError, match='must use https'):
        _resolve('tenant-1')


def test_https_and_localhost_http_broker_urls_accepted():
    # https anywhere; plain http only on the loopback (local rig / this suite).
    AccountBase._check_broker_url('https://api.rocketride.ai/db/provision')
    AccountBase._check_broker_url('http://localhost:8090/provision')
    AccountBase._check_broker_url('http://127.0.0.1:8090/provision')
    with pytest.raises(RuntimeError, match='must use https'):
        AccountBase._check_broker_url('ftp://broker.internal/provision')
    with pytest.raises(RuntimeError, match='must use https'):
        AccountBase._check_broker_url('file:///etc/passwd')


def test_dsn_without_sslmode_gets_require_pinned(broker):
    """A broker regression that drops sslmode must not silently downgrade
    every tenant connection to cleartext.
    """
    dsn = _resolve('no-sslmode-tenant')
    assert dsn == 'postgresql://r_t1_ab:secret@pooler.internal:5432/t_t1_ab?sslmode=require'


def test_dsn_with_existing_sslmode_passes_through_unchanged(broker):
    assert _resolve('tenant-1') == TEST_DSN


@pytest.mark.parametrize(
    'dsn',
    [
        'postgresql://r:p@pooler.internal:5432/t?sslmode=require',
        'postgresql://r:p@pooler.internal:5432/t?sslmode=verify-ca&sslrootcert=/etc/rr/ca.crt',
        'postgresql://r:p@pooler.internal:5432/t?sslmode=verify-full&sslrootcert=/etc/rr/ca.crt',
    ],
)
def test_broker_sslmode_that_requires_tls_passes_through(dsn):
    """The broker decides how strictly the server is verified; verify-full reaches libpq unchanged."""
    assert AccountBase._pin_dsn_tls(dsn) == dsn


@pytest.mark.parametrize('mode', ['disable', 'allow', 'prefer', 'Prefer'])
def test_broker_sslmode_without_tls_is_refused_for_a_remote_host(mode):
    with pytest.raises(RuntimeError, match=f'sslmode={mode}'):
        AccountBase._pin_dsn_tls(f'postgresql://r:p@pooler.internal:5432/t?sslmode={mode}')


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_broker_sslmode_without_tls_is_allowed_on_the_loopback(host):
    """The local development rig runs a provisioner and database without TLS."""
    dsn = f'postgresql://r:p@{host}:55433/t?sslmode=disable'
    assert AccountBase._pin_dsn_tls(dsn) == dsn


@pytest.mark.parametrize(
    'dsn',
    [
        # libpq's host / hostaddr query parameters override the host in the authority.
        'postgresql://r:p@localhost:5432/t?host=pooler.internal&sslmode=disable',
        'postgresql://r:p@127.0.0.1/t?hostaddr=203.0.113.5&sslmode=disable',
        'postgresql://r:p@localhost/t?sslmode=prefer&host=localhost,pooler.internal',
        'postgresql://r:p@localhost,pooler.internal/t?sslmode=disable',
    ],
)
def test_broker_sslmode_without_tls_is_refused_unless_every_host_is_loopback(dsn):
    with pytest.raises(RuntimeError, match='does not require TLS'):
        AccountBase._pin_dsn_tls(dsn)


@pytest.mark.parametrize(
    'dsn',
    [
        'postgresql://r:p@localhost/t?host=127.0.0.1&sslmode=disable',
        'postgresql://r:p@127.0.0.1/t?hostaddr=127.0.0.1&sslmode=disable',
        'postgresql://r:p@localhost:5432,[::1]:5433/t?sslmode=disable',
    ],
)
def test_broker_sslmode_without_tls_is_allowed_when_every_host_is_loopback(dsn):
    assert AccountBase._pin_dsn_tls(dsn) == dsn


def test_non_postgres_dsn_rejected(broker):
    with pytest.raises(RuntimeError, match='non-PostgreSQL DSN'):
        _resolve('bad-scheme-tenant')


# ---------------------------------------------------------------------------
# Legacy names: the broker settings were renamed from ROCKETRIDE_* to RR_*.
# Any value under an old name is a hard error, never a fallback.
# ---------------------------------------------------------------------------

LEGACY_SENTINEL = 'sentinel-legacy-broker-token'


@pytest.fixture()
def no_broker_env(monkeypatch):
    for name in ('RR_DB_BROKER_URL', 'RR_DB_BROKER_TOKEN', 'ROCKETRIDE_DB_BROKER_URL', 'ROCKETRIDE_DB_BROKER_TOKEN'):
        monkeypatch.delenv(name, raising=False)


def test_check_passes_with_neither_set(no_broker_env):
    from ai.account.base import check_db_broker_environment

    check_db_broker_environment()


def test_check_passes_with_only_the_new_names(no_broker_env, monkeypatch):
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv('RR_DB_BROKER_URL', 'https://broker.example/provision')
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', TEST_TOKEN)
    check_db_broker_environment()


@pytest.mark.parametrize('legacy', ['ROCKETRIDE_DB_BROKER_URL', 'ROCKETRIDE_DB_BROKER_TOKEN'])
def test_check_refuses_a_legacy_name_alone(no_broker_env, monkeypatch, legacy):
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv(legacy, LEGACY_SENTINEL)
    with pytest.raises(EnvironmentError, match=f'{legacy} -> RR_DB_BROKER_'):
        check_db_broker_environment()


@pytest.mark.parametrize('legacy_value', [TEST_TOKEN, 'a-different-token'], ids=['same-value', 'conflicting-value'])
def test_check_refuses_legacy_even_beside_the_new_name(no_broker_env, monkeypatch, legacy_value):
    """With both set, the old name is still refused."""
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv('RR_DB_BROKER_URL', 'https://broker.example/provision')
    monkeypatch.setenv('RR_DB_BROKER_TOKEN', TEST_TOKEN)
    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_TOKEN', legacy_value)
    with pytest.raises(EnvironmentError, match='renamed'):
        check_db_broker_environment()


def test_check_ignores_an_empty_legacy_name(no_broker_env, monkeypatch):
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_TOKEN', '  ')
    check_db_broker_environment()


def test_error_never_echoes_the_legacy_value(no_broker_env, monkeypatch):
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_TOKEN', LEGACY_SENTINEL)
    with pytest.raises(EnvironmentError) as caught:
        check_db_broker_environment()
    assert LEGACY_SENTINEL not in str(caught.value)


def test_resolve_refuses_legacy_names_without_calling_the_broker(no_broker_env, monkeypatch, broker):
    """resolve_db_dsn re-checks, so a legacy name cannot be used even past startup."""
    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_URL', 'http://127.0.0.1:9/provision')
    with pytest.raises(EnvironmentError):
        _resolve('tenant-1')
    assert broker.requests == []


def test_legacy_names_alone_do_not_configure_the_broker(no_broker_env, monkeypatch):
    """No fallback: the old names never become the broker configuration."""
    from ai.account.base import check_db_broker_environment

    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_URL', 'http://127.0.0.1:9/provision')
    monkeypatch.setenv('ROCKETRIDE_DB_BROKER_TOKEN', LEGACY_SENTINEL)
    with pytest.raises(EnvironmentError):
        check_db_broker_environment()
    with pytest.raises(EnvironmentError):
        _resolve('tenant-1')


def test_account_package_refuses_to_load_with_a_legacy_name(tmp_path):
    """The server fails at startup: importing ai.account runs the check."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / 'src'
    code = f'import sys\nsys.path.insert(0, {str(src)!r})\nimport ai.account\n'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RR_DB_BROKER_', 'ROCKETRIDE_DB_BROKER_'))}
    env['ROCKETRIDE_DB_BROKER_TOKEN'] = LEGACY_SENTINEL
    proc = subprocess.run(
        [sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=120, cwd=tmp_path
    )
    assert proc.returncode != 0
    assert 'ROCKETRIDE_DB_BROKER_TOKEN -> RR_DB_BROKER_TOKEN' in proc.stderr
    assert LEGACY_SENTINEL not in proc.stderr + proc.stdout


# ---------------------------------------------------------------------------
# Legacy names in the engine's .env file: refused at startup like the process
# environment (the web server loads that file only after ai.account imports).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('legacy', ['ROCKETRIDE_DB_BROKER_URL', 'ROCKETRIDE_DB_BROKER_TOKEN'])
def test_check_refuses_a_legacy_name_in_the_env_file(no_broker_env, tmp_path, legacy):
    from ai.account.base import check_db_broker_environment

    env_file = tmp_path / '.env'
    env_file.write_text(f'ROCKETRIDE_OPENAI_KEY=sk-x\n{legacy}="{LEGACY_SENTINEL}"\n', encoding='utf-8')
    with pytest.raises(EnvironmentError, match=f'{legacy} -> RR_DB_BROKER_') as caught:
        check_db_broker_environment(env_file=str(env_file))
    assert LEGACY_SENTINEL not in str(caught.value)


def test_check_accepts_an_env_file_without_legacy_names(no_broker_env, tmp_path):
    from ai.account.base import check_db_broker_environment

    env_file = tmp_path / '.env'
    env_file.write_text('RR_DB_BROKER_URL=https://broker.example\nROCKETRIDE_DB_BROKER_TOKEN=\n', encoding='utf-8')
    check_db_broker_environment(env_file=str(env_file))
    check_db_broker_environment(env_file=str(tmp_path / 'missing.env'))


def test_engine_env_file_is_next_to_the_engine(monkeypatch, tmp_path):
    import sys

    from ai.account.base import engine_env_file

    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'engine'))
    assert engine_env_file() == str(tmp_path / '.env')


def test_account_package_refuses_to_load_with_a_legacy_name_in_the_engine_env_file(tmp_path):
    """The startup check reads the engine's .env too (the web server loads it later)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    (tmp_path / '.env').write_text(f'ROCKETRIDE_DB_BROKER_TOKEN={LEGACY_SENTINEL}\n', encoding='utf-8')
    src = Path(__file__).resolve().parents[3] / 'src'
    code = (
        'import sys, types\n'
        f'sys.path.insert(0, {str(src)!r})\n'
        # Point the engine directory at tmp_path. Dependency installs (which also
        # follow sys.executable) are not under test, so they become no-ops.
        'import depends as real\n'
        "stub = types.ModuleType('depends')\n"
        'stub.__dict__.update(real.__dict__)\n'
        'stub.depends = stub.load_depends = lambda *a, **k: None\n'
        "sys.modules['depends'] = stub\n"
        f'sys.executable = {str(tmp_path / "engine")!r}\n'
        'import ai.account\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RR_DB_BROKER_', 'ROCKETRIDE_DB_BROKER_'))}
    proc = subprocess.run(
        [sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=120, cwd=tmp_path
    )
    assert proc.returncode != 0
    assert 'ROCKETRIDE_DB_BROKER_TOKEN -> RR_DB_BROKER_TOKEN' in proc.stderr
    assert LEGACY_SENTINEL not in proc.stderr + proc.stdout


# ---------------------------------------------------------------------------
# A hosted engine without broker settings warns at startup.
# ---------------------------------------------------------------------------


class _Hosted(_Minimal):
    capabilities = ('saas',)


class _OwnResolver(_Hosted):
    async def resolve_db_dsn(self, client_id):  # pragma: no cover - never called
        return 'postgresql://overlay'


@pytest.mark.parametrize(
    'account,argv,env,warns',
    [
        (_Minimal(), ['engine', '--saas'], {}, True),
        (_Hosted(), ['engine'], {}, True),
        (_Hosted(), ['engine'], {'RR_DB_BROKER_URL': 'https://b.example', 'RR_DB_BROKER_TOKEN': 't'}, False),
        (_Hosted(), ['engine'], {'RR_DB_BROKER_URL': 'https://b.example'}, True),
        (_Minimal(), ['engine'], {}, False),  # open-source default: nothing to warn about
        (_OwnResolver(), ['engine', '--saas'], {}, False),  # an overlay resolving DSNs itself needs no broker
    ],
)
def test_hosted_engine_without_broker_warns_at_startup(account, argv, env, warns):
    from ai.account.base import hosted_db_broker_warning

    text = hosted_db_broker_warning(account, argv, env)
    if warns:
        assert 'RR_DB_BROKER_URL' in text and 'not configured on this server' in text
    else:
        assert text is None


_BROKER = {'RR_DB_BROKER_URL': 'https://b.example', 'RR_DB_BROKER_TOKEN': 't'}


@pytest.mark.parametrize(
    'env,env_file,warns',
    [
        ({}, _BROKER, False),  # both settings in the engine's .env only
        ({'RR_DB_BROKER_URL': 'https://b.example'}, {'RR_DB_BROKER_TOKEN': 't'}, False),  # split across the two
        ({}, {'RR_DB_BROKER_URL': 'https://b.example'}, True),  # the token is missing everywhere
        ({}, {'RR_DB_BROKER_URL': 'https://b.example', 'RR_DB_BROKER_TOKEN': ' '}, True),  # blank in .env
        # A name already in the environment, even empty, is not replaced by .env (load_dotenv without override).
        ({'RR_DB_BROKER_TOKEN': ''}, _BROKER, True),
    ],
)
def test_hosted_warning_reads_the_engine_env_file(tmp_path, env, env_file, warns):
    from ai.account.base import hosted_db_broker_warning

    path = tmp_path / '.env'
    path.write_text(''.join(f'{name}={value}\n' for name, value in env_file.items()), encoding='utf-8')
    text = hosted_db_broker_warning(_Hosted(), ['engine'], env, env_file=str(path))
    assert (text is not None) is warns


def test_hosted_warning_without_an_env_file_reads_the_environment_only(tmp_path):
    from ai.account.base import hosted_db_broker_warning

    missing = str(tmp_path / 'absent.env')
    assert hosted_db_broker_warning(_Hosted(), ['engine'], {}, env_file=missing) is not None
    assert hosted_db_broker_warning(_Hosted(), ['engine'], dict(_BROKER), env_file=missing) is None


# ---------------------------------------------------------------------------
# OSS set_env: the former broker names cannot be set at runtime either.
# ---------------------------------------------------------------------------


def _set_env_request(env):
    return {'command': 'rrext_account_me', 'arguments': {'subcommand': 'set_env', 'env': env}}


@pytest.mark.parametrize(
    'name', ['ROCKETRIDE_DB_BROKER_URL', 'ROCKETRIDE_DB_BROKER_TOKEN', 'ROCKETRIDE_db_broker_token']
)
def test_oss_set_env_refuses_the_former_broker_names(no_broker_env, monkeypatch, tmp_path, name):
    import os
    import sys
    from unittest.mock import MagicMock

    from ai.account.oss import Account

    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'engine'))
    monkeypatch.setenv('ROCKETRIDE_GX_KEEP', 'kept')
    before = dict(os.environ)
    with pytest.raises(ValueError) as err:
        asyncio.run(
            Account().handle_account(MagicMock(), _set_env_request({'ROCKETRIDE_GX_OTHER': 'x', name: LEGACY_SENTINEL}))
        )
    assert name in str(err.value) and LEGACY_SENTINEL not in str(err.value)
    assert dict(os.environ) == before, 'nothing may change when the request is refused'
    assert not (tmp_path / '.env').exists()


def test_oss_set_env_still_saves_other_names(no_broker_env, monkeypatch, tmp_path):
    import os
    import sys
    from unittest.mock import MagicMock

    from ai.account.oss import Account

    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'engine'))
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    asyncio.run(Account().handle_account(MagicMock(), _set_env_request({'ROCKETRIDE_GX_OTHER': 'x'})))
    assert os.environ['ROCKETRIDE_GX_OTHER'] == 'x'
    assert 'ROCKETRIDE_GX_OTHER=x' in (tmp_path / '.env').read_text()
