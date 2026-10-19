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
Tests for the shared workspace ``.env`` loader and writer (rocketride_common.env).

The policy under test (documented on ``load_dot_env`` / ``write_dot_env``):

- Reading never crashes a command and is never silent about a damaged file. Bad
  UTF-8 is read as U+FFFD and the rest is applied, an assignment holding a NUL
  is skipped, and an unreadable file counts as absent; each case writes ONE
  ``Warning:`` line that names the file and a position, never any content.
- Environment-variable precedence is unchanged: the real environment wins and
  the first assignment in the file wins.
- Writing refuses a file it cannot rewrite faithfully, leaving it untouched.

Loader and writer are tested directly, and at the CLI start-up boundary
(``main()`` and a real subprocess) with no engine running.
"""

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import rocketride
import rocketride_common
from rocketride_common import env as dot_env

from rocketride.cli.commands import auth as auth_module

# `rocketride.cli.main` must be imported as a module: the `rocketride.cli`
# package re-exports the `main()` function under the same name.
cli_main = importlib.import_module('rocketride.cli.main')

# Variable names no real environment defines, so the suite is hermetic
PREFIX = 'RRTEST_DOTENV_'


@pytest.fixture(autouse=True)
def _restore_environment():
    """load_dot_env writes into os.environ; put it back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _load(tmp_path, content):
    """Write ``content`` as the workspace .env under ``tmp_path`` and load it."""
    (tmp_path / '.env').write_bytes(content)
    dot_env.load_dot_env(str(tmp_path))


def _warnings(capsys):
    """Return stderr's lines after asserting stdout stayed empty."""
    captured = capsys.readouterr()
    assert captured.out == ''
    return captured.err.splitlines()


# =========================================================================
# load_dot_env - valid files behave exactly as before
# =========================================================================


def test_valid_file_loads_silently(tmp_path, capsys):
    content = (
        f'# comment\n\nexport {PREFIX}A=one\n{PREFIX}B="two words"\n{PREFIX}C=\'three\'\n{PREFIX}A=ignored duplicate\n'
    )
    _load(tmp_path, content.encode('utf-8'))

    assert os.environ[PREFIX + 'A'] == 'one'  # the first assignment wins
    assert os.environ[PREFIX + 'B'] == 'two words'
    assert os.environ[PREFIX + 'C'] == 'three'
    assert _warnings(capsys) == []


def test_real_environment_wins_over_the_file(tmp_path, capsys):
    os.environ[PREFIX + 'A'] = 'from-shell'
    _load(tmp_path, f'{PREFIX}A=from-file\n{PREFIX}B=from-file\n'.encode('utf-8'))

    assert os.environ[PREFIX + 'A'] == 'from-shell'
    assert os.environ[PREFIX + 'B'] == 'from-file'
    assert _warnings(capsys) == []


def test_absent_file_is_silent(tmp_path, capsys):
    dot_env.load_dot_env(str(tmp_path))
    assert _warnings(capsys) == []


@pytest.mark.parametrize('newline', [b'\n', b'\r\n', b'\r'])
def test_line_endings_still_split_lines(tmp_path, capsys, newline):
    _load(tmp_path, newline.join([f'{PREFIX}A=1'.encode(), f'{PREFIX}B=2'.encode(), b'']))
    assert (os.environ[PREFIX + 'A'], os.environ[PREFIX + 'B']) == ('1', '2')
    assert _warnings(capsys) == []


# =========================================================================
# load_dot_env - invalid UTF-8
# =========================================================================


def test_invalid_utf8_applies_every_line_and_warns_once(tmp_path, capsys):
    prefix = f'{PREFIX}A=one\n{PREFIX}B=bad'.encode('utf-8')
    _load(tmp_path, prefix + b'\xffvalue\n' + f'{PREFIX}C=three\n'.encode('utf-8'))

    # the lines either side of the bad byte are applied; the bad byte is U+FFFD
    assert os.environ[PREFIX + 'A'] == 'one'
    assert os.environ[PREFIX + 'B'] == 'bad�value'
    assert os.environ[PREFIX + 'C'] == 'three'

    (line,) = _warnings(capsys)
    assert line.startswith('Warning: ')
    assert str(tmp_path / '.env') in line
    assert f'offset {len(prefix)}' in line
    assert 'line 2' in line


def test_warning_never_echoes_file_content(tmp_path, capsys):
    secret = 'sekret-token-4f9a'
    _load(tmp_path, f'{PREFIX}KEY={secret}\n{PREFIX}BAD=\xff{secret}\n{PREFIX}NUL=a\0{secret}\n'.encode('latin-1'))

    (line,) = _warnings(capsys)
    assert secret not in line
    assert PREFIX not in line


def test_line_number_counts_crlf_once(tmp_path, capsys):
    _load(tmp_path, b'A=1\r\nB=2\r\nC=\xff\r\n')
    (line,) = _warnings(capsys)
    assert 'line 3' in line


def test_precedence_survives_a_damaged_file(tmp_path, capsys):
    os.environ[PREFIX + 'A'] = 'from-shell'
    _load(tmp_path, f'{PREFIX}A=from-file\xff\n{PREFIX}B=from-file\n'.encode('latin-1'))

    assert os.environ[PREFIX + 'A'] == 'from-shell'
    assert os.environ[PREFIX + 'B'] == 'from-file'
    assert len(_warnings(capsys)) == 1


# =========================================================================
# UTF-8 byte-order mark (what Windows PowerShell 5's Set-Content -Encoding UTF8 writes)
# =========================================================================

BOM = b'\xef\xbb\xbf'


def test_leading_bom_is_not_part_of_the_first_name(tmp_path, capsys):
    # printf '\xef\xbb\xbfRRTEST_DOTENV_BOM=http://x\nRRTEST_DOTENV_B=2\n' > .env
    _load(tmp_path, BOM + f'{PREFIX}BOM=http://x\n{PREFIX}B=2\n'.encode('utf-8'))

    assert os.environ[PREFIX + 'BOM'] == 'http://x'
    assert os.environ[PREFIX + 'B'] == '2'
    assert '\ufeff' + PREFIX + 'BOM' not in os.environ
    assert _warnings(capsys) == []  # a BOM is valid UTF-8: no warning


def test_a_bom_inside_the_file_is_still_ordinary_text(tmp_path):
    # Only a LEADING mark is skipped; one elsewhere belongs to its value
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B='.encode('utf-8') + BOM + b'2\n')
    assert os.environ[PREFIX + 'B'] == '\ufeff2'


def test_write_keeps_a_bom_it_finds_and_updates_the_first_line_in_place(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(BOM + b'ROCKETRIDE_URI=http://old\nOTHER=1\n')

    dot_env.check_dot_env_writable(str(tmp_path))  # a BOM'd file is not refused
    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    # The first-line assignment is recognised (and replaced, not shadowed by an appended
    # duplicate that "first assignment wins" would ignore), and the BOM is still there once
    assert path.read_bytes() == BOM + b'ROCKETRIDE_URI=http://dev\nOTHER=1\nROCKETRIDE_APIKEY=k\n'


def test_write_never_adds_a_bom(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'OTHER=1\n')
    dot_env.write_dot_env({'A': '1'}, str(tmp_path))
    assert path.read_bytes() == b'OTHER=1\nA=1\n'


# =========================================================================
# load_dot_env - NUL characters
# =========================================================================


def test_nul_assignments_are_skipped_and_the_rest_applied(tmp_path, capsys):
    # os.environ.setdefault raises ValueError on a NUL in a name or value; the
    # lines before AND after must still be applied, and nothing may be half-applied
    before = set(os.environ)
    _load(
        tmp_path,
        f'{PREFIX}A=1\n{PREFIX}N\0AME=2\n{PREFIX}V=a\0b\n{PREFIX}B=2\n'.encode('utf-8'),
    )

    assert os.environ[PREFIX + 'A'] == '1'
    assert os.environ[PREFIX + 'B'] == '2'
    assert set(os.environ) - before == {PREFIX + 'A', PREFIX + 'B'}

    (line,) = _warnings(capsys)
    assert 'NUL' in line
    assert '2 assignment lines' in line
    assert 'first on line 2' in line


@pytest.mark.parametrize('encoding', ['utf-16', 'utf-16-le'], ids=['with-bom', 'without-bom'])
def test_utf16_file_neither_crashes_nor_sets_anything(tmp_path, capsys, encoding):
    # What Windows PowerShell 5's `>` writes
    before = dict(os.environ)
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B=2\n'.encode(encoding))

    assert dict(os.environ) == before
    (line,) = _warnings(capsys)
    assert 'UTF-16' in line


def test_deploy_pair_in_a_file_with_a_nul_line_is_still_applied(tmp_path, capsys):
    # The prod deploy pair must be visible to `login`, which refuses to
    # overwrite a deploy pair that points elsewhere
    _load(tmp_path, b'RRTEST_DOTENV_DEPLOY_URI=https://prod.example\nNOTE=a\0b\n')
    assert os.environ[PREFIX + 'DEPLOY_URI'] == 'https://prod.example'
    assert len(_warnings(capsys)) == 1


# =========================================================================
# load_dot_env - unreadable or not a file
# =========================================================================


def test_directory_named_env_is_skipped_silently(tmp_path, capsys):
    # `python -m venv .env` is a common layout; it has never been read as a file
    (tmp_path / '.env').mkdir()
    before = dict(os.environ)
    dot_env.load_dot_env(str(tmp_path))

    assert dict(os.environ) == before
    assert _warnings(capsys) == []


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes are not available on this platform')
def test_fifo_named_env_warns_without_blocking_on_it(tmp_path, capsys):
    os.mkfifo(tmp_path / '.env')
    before = dict(os.environ)
    dot_env.load_dot_env(str(tmp_path))  # opening a FIFO with no writer would block

    assert dict(os.environ) == before
    (line,) = _warnings(capsys)
    assert 'not a regular file' in line


def test_a_skipped_nul_line_does_not_shadow_a_later_assignment(tmp_path, capsys):
    # The first USABLE assignment of a variable wins; the warning names the skipped line
    _load(tmp_path, f'{PREFIX}URI=https://prod\0\n{PREFIX}URI=http://localhost\n'.encode('utf-8'))

    assert os.environ[PREFIX + 'URI'] == 'http://localhost'
    (line,) = _warnings(capsys)
    assert 'first on line 1' in line


def test_unreadable_file_warns_and_is_treated_as_absent(tmp_path, capsys, monkeypatch):
    (tmp_path / '.env').write_text(f'{PREFIX}A=1\n', encoding='utf-8')

    def deny(*_args, **_kwargs):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(dot_env, 'open', deny, raising=False)
    before = dict(os.environ)
    dot_env.load_dot_env(str(tmp_path))

    assert dict(os.environ) == before
    (line,) = _warnings(capsys)
    assert 'Permission denied' in line
    assert PREFIX not in line


@pytest.mark.skipif(
    os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0),
    reason='chmod 000 does not stop Windows, or root, from reading a file',
)
def test_file_without_read_permission_warns_and_is_treated_as_absent(tmp_path, capsys):
    path = tmp_path / '.env'
    path.write_text(f'{PREFIX}A=1\n', encoding='utf-8')
    path.chmod(0)
    try:
        before = dict(os.environ)
        dot_env.load_dot_env(str(tmp_path))
    finally:
        path.chmod(0o600)

    assert dict(os.environ) == before
    (line,) = _warnings(capsys)
    assert 'cannot be read' in line


@pytest.mark.parametrize('stream', ['none', 'closed', 'broken'])
def test_unwritable_stderr_never_turns_a_warning_into_a_crash(tmp_path, monkeypatch, stream):
    class _Broken:
        def write(self, _text):
            raise OSError('broken pipe')

        def flush(self):
            raise OSError('broken pipe')

    class _Closed:
        def write(self, _text):
            raise ValueError('I/O operation on closed file')

        def flush(self):
            raise ValueError('I/O operation on closed file')

    monkeypatch.setattr(sys, 'stderr', {'none': None, 'closed': _Closed(), 'broken': _Broken()}[stream])
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B=\xff\n'.encode('latin-1'))
    assert os.environ[PREFIX + 'A'] == '1'


# =========================================================================
# write_dot_env - refuses what it cannot rewrite faithfully
# =========================================================================

PROD_LINE = b'ROCKETRIDE_DEPLOY_URI=https://prod.example\n'


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        (PROD_LINE + b'NOTE=\xff\n', 'not valid UTF-8'),
        (PROD_LINE + b'NOTE=a\0b\n', 'NUL'),
        (PROD_LINE + 'ROCKETRIDE_URI=http://x\n'.encode('utf-16'), 'not valid UTF-8'),
        (PROD_LINE + 'ROCKETRIDE_URI=http://x\n'.encode('utf-16-le'), 'NUL'),
    ],
    ids=['invalid-utf8', 'nul', 'utf16-bom', 'utf16-no-bom'],
)
def test_write_refuses_an_unfaithful_file_and_leaves_it_untouched(tmp_path, content, expected):
    path = tmp_path / '.env'
    path.write_bytes(content)

    with pytest.raises(dot_env.DotEnvError) as error:
        dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_DEPLOY_URI': 'http://dev'}, str(tmp_path))

    message = str(error.value)
    assert str(path) in message
    assert expected in message
    assert 'prod.example' not in message  # no contents in the diagnostic
    assert '\n' not in message  # one line
    assert path.read_bytes() == content


def test_write_refuses_a_directory_and_an_unreadable_file(tmp_path, monkeypatch):
    (tmp_path / '.env').mkdir()
    with pytest.raises(dot_env.DotEnvError, match='not a regular file'):
        dot_env.write_dot_env({'A': '1'}, str(tmp_path))

    other = tmp_path / 'other'
    other.mkdir()
    (other / '.env').write_text('A=1\n', encoding='utf-8')

    def deny(*_args, **_kwargs):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(dot_env, 'open', deny, raising=False)
    with pytest.raises(dot_env.DotEnvError, match='Permission denied'):
        dot_env.write_dot_env({'A': '2'}, str(other))


def test_check_writable_reports_the_same_refusal_without_writing(tmp_path):
    (tmp_path / '.env').write_bytes(b'A=\xff\n')
    with pytest.raises(dot_env.DotEnvError, match='not valid UTF-8'):
        dot_env.check_dot_env_writable(str(tmp_path))
    dot_env.check_dot_env_writable(str(tmp_path / 'nowhere'))  # absent: fine


def test_write_still_preserves_a_valid_file_line_for_line(tmp_path):
    path = tmp_path / '.env'
    path.write_text(
        '# keep me\nROCKETRIDE_DEPLOY_URI=https://prod.example\nROCKETRIDE_URI=http://old\n\nOTHER=1\n',
        encoding='utf-8',
    )
    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    assert path.read_text(encoding='utf-8') == (
        '# keep me\nROCKETRIDE_DEPLOY_URI=https://prod.example\nROCKETRIDE_URI=http://dev\n\nOTHER=1\nROCKETRIDE_APIKEY=k\n'
    )


# =========================================================================
# CLI start-up boundary (no engine)
# =========================================================================


def _command(tmp_path, argv, env_content=b''):
    """Run the real CLI entry point in ``tmp_path`` with ``env_content`` as its .env."""
    if env_content is not None:
        (tmp_path / '.env').write_bytes(env_content)
    env = {key: value for key, value in os.environ.items() if not key.startswith('ROCKETRIDE_')}
    # Both source roots go onto sys.path INSIDE the child: in CI sys.executable is
    # the engine's isolated interpreter, which ignores PYTHONPATH.
    roots = [
        str(Path(rocketride.__file__).resolve().parents[1]),
        str(Path(rocketride_common.__file__).resolve().parents[1]),
    ]
    return subprocess.run(
        [
            sys.executable,
            '-c',
            f'import sys; sys.path[:0] = {roots!r}; from rocketride.cli.main import main; main()',
            *argv,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )


# One command per failure the review named, each ending without a server:
# `list --help` is parsed (not run), `validate` fails on a missing file before it
# connects, and `start` fails on a missing pipeline file.
_AFFECTED_COMMANDS = [
    pytest.param(['list', '--help'], 0, 'usage:', id='list'),
    pytest.param(['validate', 'no-such.pipe'], 2, 'File not found', id='validate'),
    pytest.param(['start', '--pipeline', 'no-such.pipe', '--apikey', 'k'], 1, 'no-such.pipe', id='start'),
]


@pytest.mark.parametrize(('argv', 'code', 'marker'), _AFFECTED_COMMANDS)
@pytest.mark.parametrize(
    'content',
    [b'X=\xff\n', b'X=a\0b\n', 'X=1\n'.encode('utf-16')],
    ids=['invalid-utf8', 'nul', 'utf16'],
)
def test_damaged_env_does_not_crash_the_command(tmp_path, argv, code, marker, content):
    result = _command(tmp_path, argv, content)

    assert 'Traceback' not in result.stderr
    assert result.returncode == code, result.stderr
    assert marker in result.stdout + result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.startswith('Warning: ')]
    assert len(warnings) == 1
    assert str(tmp_path / '.env') in warnings[0]


def test_valid_env_prints_no_warning_at_the_cli_boundary(tmp_path):
    result = _command(tmp_path, ['list', '--help'], b'X=1\n')
    assert result.returncode == 0
    assert 'Warning' not in result.stderr


def test_main_applies_the_valid_lines_of_a_damaged_env_with_env_precedence(tmp_path, monkeypatch, capsys):
    # What `main()` builds the parser from: the file's valid lines are in effect
    # (the URI), the shell wins over the file (the API key), and the bad line only warns
    (tmp_path / '.env').write_bytes(b'ROCKETRIDE_URI=http://from-dotenv\nROCKETRIDE_APIKEY=from-file\nX=\xff\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('ROCKETRIDE_URI', raising=False)
    monkeypatch.setenv('ROCKETRIDE_APIKEY', 'from-shell')
    seen = []

    async def _dispatch(args):
        seen.append(args)
        return 0

    monkeypatch.setattr(cli_main, '_dispatch', _dispatch)
    monkeypatch.setattr(sys, 'argv', ['rocketride', 'list'])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()

    assert exit_info.value.code == 0
    assert (seen[0].uri, seen[0].apikey) == ('http://from-dotenv', 'from-shell')
    captured = capsys.readouterr()
    assert [line.startswith('Warning: ') for line in captured.err.splitlines()] == [True]
    monkeypatch.delenv('ROCKETRIDE_URI', raising=False)


# =========================================================================
# `login` - a prod deploy line survives a .env the writer cannot rewrite
# =========================================================================


def _login(tmp_path, monkeypatch, capsys, env_content):
    """Run `rocketride login` against a stubbed server with ``env_content`` as the .env."""
    (tmp_path / '.env').write_bytes(env_content)
    monkeypatch.chdir(tmp_path)
    for name in (
        'ROCKETRIDE_URI',
        'ROCKETRIDE_APIKEY',
        'ROCKETRIDE_DEPLOY_URI',
        'ROCKETRIDE_DEPLOY_APIKEY',
    ):
        monkeypatch.delenv(name, raising=False)
    # What main() does before dispatch
    dot_env.load_dot_env()
    contacted = []

    async def _server_info(uri):
        contacted.append(('probe', uri))
        return {'version': '1.0', 'capabilities': []}

    async def _connect(uri, apikey=''):
        contacted.append(('connect', uri))

    async def _disconnect():
        return None

    monkeypatch.setattr(rocketride.RocketRideClient, 'get_server_info', staticmethod(_server_info))
    monkeypatch.setattr(auth_module, 'connect_client', _connect)
    monkeypatch.setattr(auth_module, 'disconnect_all', _disconnect)
    args = SimpleNamespace(uri='http://dev.example', apikey='dev-key', json=None, deploy=True, deploy_pair=False)
    code = asyncio.run(auth_module.run_login(args))
    return code, contacted, capsys.readouterr()


@pytest.mark.parametrize(
    'bad_line', [b'NOTE=\xff\n', b'NOTE=a\0b\n', 'X=1\n'.encode('utf-16-le')], ids=['invalid-utf8', 'nul', 'utf16']
)
def test_login_leaves_a_prod_deploy_line_alone_when_the_env_is_damaged(tmp_path, monkeypatch, capsys, bad_line):
    content = PROD_LINE + bad_line
    code, contacted, captured = _login(tmp_path, monkeypatch, capsys, content)

    assert code == 1
    assert (tmp_path / '.env').read_bytes() == content  # the prod line, and every byte, untouched
    assert 'Refusing to update' in captured.err
    assert str(tmp_path / '.env') in captured.err
    assert 'prod.example' not in captured.err
    assert contacted == []  # refused before any probe, prompt or connection


def test_login_keeps_a_prod_deploy_line_in_a_healthy_env(tmp_path, monkeypatch, capsys):
    # The control: with a usable .env the same flow succeeds, writes the dev pair
    # and does not mirror it over the deploy pair that points elsewhere
    code, contacted, captured = _login(tmp_path, monkeypatch, capsys, PROD_LINE + b'NOTE=fine\n')

    assert code == 0, captured.err
    assert contacted == [('probe', 'http://dev.example'), ('connect', 'http://dev.example')]
    written = (tmp_path / '.env').read_text(encoding='utf-8')
    assert 'ROCKETRIDE_DEPLOY_URI=https://prod.example\n' in written
    assert 'ROCKETRIDE_URI=http://dev.example\n' in written
    assert 'ROCKETRIDE_DEPLOY_APIKEY' not in written


def test_login_cli_refuses_a_damaged_env_without_a_traceback(tmp_path):
    content = PROD_LINE + b'NOTE=\xff\n'
    # Unroutable URI: the refusal must come before any connection attempt
    result = _command(tmp_path, ['login', '--uri', 'http://127.0.0.1:1', '--apikey', 'k'], content)

    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert 'Refusing to update' in result.stderr
    assert 'Probing' not in result.stdout
    assert (tmp_path / '.env').read_bytes() == content
