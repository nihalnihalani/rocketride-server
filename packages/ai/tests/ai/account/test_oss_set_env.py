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

"""The open-source ``set_env`` command and the engine's ``.env`` file.

``set_env`` puts ROCKETRIDE_* names into the process environment and into the
``.env`` file next to the engine, which the web server loads (python-dotenv)
at the next start. Every name and value must come back from that file as one
assignment of exactly that value. Otherwise a caller could add a line (an
operator-only RR_DB_BROKER_* setting, or a former broker name that stops the
engine from starting), absorb the operator's own lines into a value that
``get_env`` returns, or have the loader expand another setting into one.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values

from ai.account import oss
from ai.account.oss import Account

SECRET = 'sentinel-set-env-value'
BROKER_URL = 'https://broker.example/provision'
BROKER_TOKEN = 'operator-broker-token'
ENV_FILE = (
    f'ROCKETRIDE_GX_KEEP=kept\n# operator settings\nRR_DB_BROKER_URL={BROKER_URL}\nRR_DB_BROKER_TOKEN={BROKER_TOKEN}\n'
)

# The engine binary that runs these tests, taken before a fixture points
# sys.executable at a test's engine directory.
ENGINE = sys.executable


def _set_env(env):
    request = {'command': 'rrext_account_me', 'arguments': {'subcommand': 'set_env', 'env': env}}
    return asyncio.run(Account().handle_account(MagicMock(), request))


@pytest.fixture
def engine_dir(monkeypatch, tmp_path):
    """An engine whose .env has one ROCKETRIDE_ line above the operator's broker settings.

    os.environ is a small private dict, so a failure's diff never prints the
    real environment.
    """
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'engine'))
    environ = {'ROCKETRIDE_GX_KEEP': 'kept', 'RR_DB_BROKER_URL': BROKER_URL, 'RR_DB_BROKER_TOKEN': BROKER_TOKEN}
    monkeypatch.setattr(os, 'environ', environ)
    (tmp_path / '.env').write_text(ENV_FILE, encoding='utf-8')
    return tmp_path


def _rocketride_environ():
    return {k: v for k, v in os.environ.items() if k.startswith('ROCKETRIDE_')}


@pytest.fixture
def real_environ_engine_dir(monkeypatch, tmp_path):
    """As ``engine_dir``, but with the process's real os.environ, which encodes
    what it is given as the engine's does (a plain dict takes anything).

    The real ROCKETRIDE_* entries are set aside for the test and put back
    afterwards, and only ROCKETRIDE_* entries are compared, so a failure's
    diff shows only the test's own names.
    """
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'engine'))
    saved = _rocketride_environ()
    for name in saved:
        del os.environ[name]
    os.environ['ROCKETRIDE_GX_KEEP'] = 'kept'
    (tmp_path / '.env').write_text(ENV_FILE, encoding='utf-8')
    try:
        yield tmp_path
    finally:
        for name in _rocketride_environ():
            del os.environ[name]
        os.environ.update(saved)


def _assert_refused(engine_dir, env) -> str:
    """``set_env(env)`` raises ValueError and changes neither os.environ nor the .env file."""
    environ_before = dict(os.environ)
    file_before = (engine_dir / '.env').read_text(encoding='utf-8')
    with pytest.raises(ValueError) as caught:
        _set_env(env)
    assert dict(os.environ) == environ_before, 'nothing may change when the request is refused'
    assert (engine_dir / '.env').read_text(encoding='utf-8') == file_before
    message = str(caught.value)
    assert SECRET not in message, 'a refused value is never echoed'
    return message


@pytest.mark.parametrize(
    'char',
    ['\n', '\r', '\r\n', '\x00', '\t', '\x0b', '\x0c', '\x1c', '\x1f', '\x7f', '\x85', '\u2028', '\u2029'],
)
def test_a_line_break_or_control_character_in_a_value_is_refused(engine_dir, char):
    """A newline in a value would add its own line to the .env file: here an
    operator-only broker URL, which would receive the broker token at the
    next task start.
    """
    value = f'{SECRET}{char}RR_DB_BROKER_URL=https://elsewhere.example/p'
    message = _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_VALUE': value})
    assert 'ROCKETRIDE_GX_VALUE' in message


@pytest.mark.parametrize(
    'name',
    [
        'ROCKETRIDE_GX_A\nRR_DB_BROKER_URL',
        'ROCKETRIDE_GX_A\rROCKETRIDE_DB_BROKER_TOKEN',
        'ROCKETRIDE_GX_A=RR_DB_BROKER_URL',
        'ROCKETRIDE_GX A',
        'ROCKETRIDE_GX-A',
        'ROCKETRIDE_GX_\u00c4',
        'ROCKETRIDE_GX#A',
        'ROCKETRIDE_',
    ],
)
def test_a_name_that_is_not_a_plain_identifier_is_refused(engine_dir, name):
    _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', name: SECRET})


@pytest.mark.parametrize(
    'name',
    [
        'RR_DB_BROKER_URL',
        'RR_DB_BROKER_TOKEN',
        'rr_db_broker_token',
        ' RR_DB_BROKER_URL',
        'RR_DB_BROKER_TOKEN\n',
        'ROCKETRIDE_DB_BROKER_URL',
        'ROCKETRIDE_Db_Broker_Token',
        'ROCKETRIDE_DB_BROKER_URL ',
        'ROCKETRIDE_DB_BROKER_TOKEN\t',
    ],
)
def test_the_broker_settings_are_refused_however_they_are_spelled(engine_dir, name):
    """Operator-only settings and their former names: refused, never silently ignored or written."""
    message = _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', name: SECRET})
    assert repr(name) in message
    assert 'RR_DB_BROKER_URL and RR_DB_BROKER_TOKEN' in message


@pytest.mark.parametrize(
    'value',
    [f'${{RR_DB_BROKER_TOKEN}}{SECRET}', f'{SECRET}-${{RR_DB_BROKER_URL:-x}}', f'${{ROCKETRIDE_GX_KEEP}}{SECRET}'],
)
def test_a_value_the_env_loader_would_expand_is_refused(engine_dir, value):
    """python-dotenv expands ${NAME} in every value, quoted or not, from the
    engine's environment: ${RR_DB_BROKER_TOKEN} would come back from get_env
    (and reach every task) as the broker token.
    """
    message = _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_VALUE': value})
    assert 'ROCKETRIDE_GX_VALUE' in message


@pytest.mark.parametrize(
    'value', ['\udc80', f'{SECRET}\udcff', '\ud800', '\udfff'], ids=['dc80', 'text-dcff', 'd800', 'dfff']
)
@pytest.mark.parametrize('name', ['ROCKETRIDE_GX_KEEP', 'ROCKETRIDE_GX_ADDED'], ids=['existing-name', 'new-name'])
def test_a_surrogate_in_a_value_is_refused_and_the_env_file_keeps_every_byte(real_environ_engine_dir, name, value):
    """json.loads turns the escape "\\udc80" in a request into a lone
    surrogate. The real os.environ accepts U+DC80 to U+DCFF (surrogateescape),
    but UTF-8 cannot encode any surrogate: written to the .env file, the value
    would fail after the file was opened, and empty it, taking the operator's
    broker settings and every other line with it.
    """
    env_file = real_environ_engine_dir / '.env'
    file_before = env_file.read_bytes()
    environ_before = _rocketride_environ()

    with pytest.raises(ValueError) as caught:
        _set_env({'ROCKETRIDE_GX_KEEP': 'kept', name: value})

    assert env_file.read_bytes() == file_before, 'the .env file must keep every byte'
    assert _rocketride_environ() == environ_before, 'nothing may change when the request is refused'
    assert not isinstance(caught.value, UnicodeError), f'refused by a failed encode, not a check: {caught.value!r}'
    message = str(caught.value)
    assert name in message and SECRET not in message


def test_a_quoted_value_ending_in_a_backslash_is_refused(engine_dir):
    """Such a value needs quotes in the file, and older python-dotenv releases
    read a backslash before the closing quote as an escaped quote.
    """
    message = _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_VALUE': f' {SECRET}\\'})
    assert 'ROCKETRIDE_GX_VALUE' in message


@pytest.mark.parametrize('env', [{'ROCKETRIDE_GX_VALUE': 5}, {'ROCKETRIDE_GX_VALUE': None}, ['ROCKETRIDE_GX_VALUE']])
def test_a_non_string_value_or_a_non_object_env_is_refused(engine_dir, env):
    _assert_refused(engine_dir, env)


def _not_utf8(env_file) -> bytes:
    data = b'ROCKETRIDE_GX_KEEP=kept\n# operator note \xff\n'
    env_file.write_bytes(data)
    return data


def _read_only(env_file) -> bytes:
    data = env_file.read_bytes()
    env_file.chmod(0o444)
    return data


def _unreadable(env_file) -> bytes:
    data = env_file.read_bytes()
    env_file.chmod(0o000)
    return data


def _read_only_directory(env_file) -> bytes:
    data = env_file.read_bytes()
    env_file.parent.chmod(0o555)
    return data


@pytest.mark.skipif(not hasattr(os, 'geteuid') or os.geteuid() == 0, reason='file modes do not bind root')
@pytest.mark.parametrize(
    'break_file,error',
    [
        (_not_utf8, UnicodeDecodeError),
        (_read_only, PermissionError),
        (_unreadable, PermissionError),
        (_read_only_directory, PermissionError),
    ],
    ids=['not-utf8', 'read-only', 'unreadable', 'read-only-directory'],
)
def test_an_env_file_that_cannot_be_read_or_written_fails_the_request_and_changes_nothing(
    engine_dir, break_file, error
):
    """A request that passed every check can still fail on the file: here it
    is not UTF-8, cannot be read, cannot be written, or sits in a directory
    the new file cannot be written to. The request then fails with the process
    environment as it was, and the file as it was: a read-only file is not
    replaced either.
    """
    env_file = engine_dir / '.env'
    file_before = break_file(env_file)
    environ_before = dict(os.environ)
    try:
        with pytest.raises(error):
            _set_env({'ROCKETRIDE_GX_KEEP': 'changed', 'ROCKETRIDE_GX_ADDED': SECRET})
    finally:
        engine_dir.chmod(0o755)
        env_file.chmod(0o644)
    assert dict(os.environ) == environ_before, 'a failed request must leave the environment as it was'
    assert env_file.read_bytes() == file_before
    assert sorted(p.name for p in engine_dir.iterdir()) == ['.env'], 'no partly written file is left behind'


# Runs set_env in a separate engine process whose files cannot grow past a few
# bytes (RLIMIT_FSIZE, as on a full disk), so writing the .env file fails
# partway. The engine binary does not read PYTHONPATH, so the script puts this
# checkout first on sys.path itself.
_WRITE_FAILS_PARTWAY = """
import asyncio, json, os, resource, signal, sys

sys.path.insert(0, @SRC@)
from unittest.mock import MagicMock

from ai.account import oss

engine_dir, limit, env = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
sys.executable = os.path.join(engine_dir, 'engine')
request = {'command': 'rrext_account_me', 'arguments': {'subcommand': 'set_env', 'env': env}}


def rocketride():
    return {k: v for k, v in os.environ.items() if k.startswith('ROCKETRIDE_')}


before = rocketride()
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
try:
    asyncio.run(oss.Account().handle_account(MagicMock(), request))
    error = None
except OSError as e:
    error = [type(e).__name__, e.errno]
finally:
    resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
report = {'module': oss.__file__, 'error': error, 'environ_unchanged': rocketride() == before}
print('REPORT ' + json.dumps(report), flush=True)
"""


@pytest.mark.skipif(not hasattr(signal, 'SIGXFSZ'), reason='needs RLIMIT_FSIZE and SIGXFSZ (Linux, macOS)')
def test_a_write_that_fails_partway_leaves_the_env_file_whole(tmp_path):
    """The .env file holds the operator's lines (here the broker settings). A
    write that fails partway, as on a full disk, must leave them all there,
    and the process environment as it was.
    """
    src = Path(oss.__file__).resolve().parents[3]
    script = tmp_path / 'write_fails_partway.py'
    script.write_text(_WRITE_FAILS_PARTWAY.replace('@SRC@', repr(str(src))), encoding='utf-8')
    engine_dir = tmp_path / 'engine'
    engine_dir.mkdir()
    env_file = engine_dir / '.env'
    env_file.write_text(ENV_FILE, encoding='utf-8')
    file_before = env_file.read_bytes()
    environ = {k: v for k, v in os.environ.items() if not k.startswith('ROCKETRIDE_')}
    environ['ROCKETRIDE_GX_KEEP'] = 'kept'
    request_env = {'ROCKETRIDE_GX_KEEP': 'changed', 'ROCKETRIDE_GX_ADDED': SECRET * 4}

    proc = subprocess.run(
        [ENGINE, str(script), str(engine_dir), '16', json.dumps(request_env)],
        cwd=os.path.dirname(ENGINE),
        env=environ,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = proc.stdout + proc.stderr
    reports = [line[len('REPORT ') :] for line in proc.stdout.splitlines() if line.startswith('REPORT ')]
    assert len(reports) == 1, output
    report = json.loads(reports[0])
    assert Path(report['module']).resolve() == Path(oss.__file__).resolve(), 'the engine process runs this checkout'
    assert report['error'] == ['OSError', errno.EFBIG], output
    assert report['environ_unchanged'], 'a failed request must leave the environment as it was'
    assert env_file.read_bytes() == file_before, "a failed write must leave every one of the operator's lines"
    assert sorted(p.name for p in engine_dir.iterdir()) == ['.env'], 'no partly written file is left behind'


def test_a_symlinked_env_file_keeps_its_link(engine_dir, tmp_path_factory):
    """An operator's .env that links to a file elsewhere stays a link; the file it points to gets the change."""
    target = tmp_path_factory.mktemp('config') / 'engine.env'
    target.write_text(ENV_FILE, encoding='utf-8')
    link = engine_dir / '.env'
    link.unlink()
    link.symlink_to(target)

    _set_env({'ROCKETRIDE_GX_KEEP': 'changed'})

    assert link.is_symlink() and Path(os.readlink(link)) == target
    assert dict(dotenv_values(target)) == {
        'ROCKETRIDE_GX_KEEP': 'changed',
        'RR_DB_BROKER_URL': BROKER_URL,
        'RR_DB_BROKER_TOKEN': BROKER_TOKEN,
    }
    assert sorted(p.name for p in engine_dir.iterdir()) == ['.env']


@pytest.mark.skipif(not hasattr(os, 'geteuid'), reason='POSIX permission bits')
def test_the_env_file_keeps_its_permission_bits(engine_dir):
    env_file = engine_dir / '.env'
    env_file.chmod(0o640)

    _set_env({'ROCKETRIDE_GX_KEEP': 'changed'})

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
    assert dotenv_values(env_file)['ROCKETRIDE_GX_KEEP'] == 'changed'


@pytest.mark.skipif(not hasattr(os, 'geteuid'), reason='POSIX permission bits')
def test_a_new_env_file_is_readable_and_writable_by_the_engine_user_only(engine_dir):
    """The .env file holds settings such as ROCKETRIDE_APIKEY."""
    (engine_dir / '.env').unlink()

    _set_env({'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_ADDED': SECRET})

    env_file = engine_dir / '.env'
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert dict(dotenv_values(env_file)) == {'ROCKETRIDE_GX_ADDED': SECRET, 'ROCKETRIDE_GX_KEEP': 'kept'}


def test_every_value_comes_back_from_the_env_file_exactly(engine_dir):
    """Whatever the value, the file holds exactly that value under exactly that
    name, and the operator's lines stay as they were: an opening quote on the
    line above them cannot pull them into a ROCKETRIDE_ value.
    """
    values = {
        'ROCKETRIDE_GX_KEEP': '"',
        'ROCKETRIDE_GX_ZZ_CLOSE': 'end"',
        'ROCKETRIDE_GX_PLAIN': 'x',
        'ROCKETRIDE_GX_HASH': 'abc #not-a-comment',
        'ROCKETRIDE_GX_HASH_FIRST': '#x',
        'ROCKETRIDE_GX_PADDED': '  padded  ',
        'ROCKETRIDE_GX_DOUBLE_QUOTED': '"quoted"',
        'ROCKETRIDE_GX_APOSTROPHE': "it's",
        'ROCKETRIDE_GX_LEADING_QUOTE': "'x",
        'ROCKETRIDE_GX_WINDOWS_PATH': 'C:\\data\\',
        'ROCKETRIDE_GX_ESCAPES': "a\\'b\\\\c",
        'ROCKETRIDE_GX_QUOTED_ESCAPES': " a\\'b\\\\c '",
        'ROCKETRIDE_GX_DOLLAR': '$HOME and $',
        'ROCKETRIDE_GX_EQUALS': 'a=b',
        'ROCKETRIDE_GX_EMPTY': '',
        'ROCKETRIDE_GX_UNICODE': 'h\u00e9llo \u2713',
    }

    _set_env(values)

    assert {name: os.environ[name] for name in values} == values
    loaded = dotenv_values(engine_dir / '.env')
    assert dict(loaded) == {**values, 'RR_DB_BROKER_URL': BROKER_URL, 'RR_DB_BROKER_TOKEN': BROKER_TOKEN}


@pytest.mark.parametrize(
    'last_line',
    ['RR_DB_BROKER_URL=https://broker.example', f'RR_DB_BROKER_TOKEN={BROKER_TOKEN}', '# operator note'],
    ids=['broker-url', 'broker-token', 'comment'],
)
def test_a_name_set_env_adds_never_joins_a_last_line_without_a_line_break(engine_dir, last_line):
    """An operator's .env need not end with a line break. A name set_env adds
    goes on a line of its own: appended to the operator's last line, the
    caller's text would become part of the broker URL or token, or vanish
    into a comment.
    """
    env_file = engine_dir / '.env'
    env_file.write_text(f'ROCKETRIDE_GX_KEEP=kept\n# operator settings\n{last_line}', encoding='utf-8')
    operator_before = {k: v for k, v in dotenv_values(env_file).items() if not k.startswith('ROCKETRIDE_')}

    _set_env({'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_ADDED': 'x.elsewhere.example/p'})

    assert env_file.read_text(encoding='utf-8').splitlines() == [
        'ROCKETRIDE_GX_KEEP=kept',
        '# operator settings',
        last_line,
        'ROCKETRIDE_GX_ADDED=x.elsewhere.example/p',
    ]
    loaded = dotenv_values(env_file)
    assert {k: v for k, v in loaded.items() if not k.startswith('ROCKETRIDE_')} == operator_before
    assert loaded['ROCKETRIDE_GX_ADDED'] == 'x.elsewhere.example/p'


def test_a_plain_value_is_written_unquoted(engine_dir):
    """Ordinary values keep the file's existing NAME=value form."""
    _set_env({'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_OTHER': 'https://example.com/a?b=c'})

    lines = (engine_dir / '.env').read_text(encoding='utf-8').splitlines()
    assert lines == [
        'ROCKETRIDE_GX_KEEP=kept',
        '# operator settings',
        f'RR_DB_BROKER_URL={BROKER_URL}',
        f'RR_DB_BROKER_TOKEN={BROKER_TOKEN}',
        'ROCKETRIDE_GX_OTHER=https://example.com/a?b=c',
    ]
