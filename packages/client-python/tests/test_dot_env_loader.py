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

- Reading never crashes a command and is never silent about a damaged file. Every
  line is judged on its own: an assignment holding an invalid UTF-8 byte or a NUL,
  or a name or value this process's environment cannot hold (non-ASCII text under
  an ASCII filesystem encoding, as in the engine's embedded interpreter on Linux),
  is skipped, never altered, and every other line is applied. An unreadable file
  counts as absent. Each case writes ONE ``Warning:`` line that names the file and
  positions and counts, never any content.
- Environment-variable precedence is unchanged: the real environment wins and
  the first usable assignment in the file wins.
- Writing refuses a file it cannot rewrite faithfully, leaving it untouched, and
  keeps the line endings the file already has.

Loader and writer are tested directly, and at the CLI start-up boundary
(``main()`` and a real subprocess) with no engine running.
"""

import asyncio
import collections.abc
import importlib
import json
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


class _AsciiEnviron(collections.abc.MutableMapping):
    """
    A stand-in for ``os.environ`` that stores names and values the way POSIX does under
    an ASCII filesystem encoding: encoded with ``surrogateescape``, so any non-ASCII
    text raises ``UnicodeEncodeError`` on assignment and nothing is stored.
    """

    def __init__(self, data=None):
        self._data = dict(data or {})

    @staticmethod
    def _encode(text):
        if not isinstance(text, str):
            raise TypeError(f'str expected, not {type(text).__name__}')
        return text.encode('ascii', 'surrogateescape')

    def __getitem__(self, key):
        return self._data[self._encode(key)].decode('ascii', 'surrogateescape')

    def __setitem__(self, key, value):
        name, text = self._encode(key), self._encode(value)
        if b'\0' in name or b'\0' in text or not name or b'=' in name:
            raise ValueError('illegal environment variable name or value')
        self._data[name] = text

    def __delitem__(self, key):
        del self._data[self._encode(key)]

    def __iter__(self):
        return (name.decode('ascii', 'surrogateescape') for name in self._data)

    def __len__(self):
        return len(self._data)


@pytest.fixture
def ascii_filesystem(monkeypatch):
    """
    Make this process look like the engine's embedded interpreter on Linux, whose
    filesystem encoding is ASCII, on any platform: the environment, ``os.fsencode``
    and the encoding name all follow it. Returns the (initially empty) environment.
    """
    environ = _AsciiEnviron()
    monkeypatch.setattr(os, 'environ', environ)
    monkeypatch.setattr(os, 'fsencode', lambda value: value.encode('ascii', 'surrogateescape'))
    monkeypatch.setattr(sys, 'getfilesystemencoding', lambda: 'ascii')
    return environ


@pytest.fixture
def any_text_environ(monkeypatch):
    """
    Replace ``os.environ`` with a plain dict, which stores any text.

    The tests that look at U+FEFF or U+FFFD in a stored value or name are about what the
    loader reads, not about what an ASCII-encoded process can hold (see
    ``ascii_filesystem`` for that), so they must not depend on the filesystem encoding.
    """
    environ = {}
    monkeypatch.setattr(os, 'environ', environ)
    return environ


def _load(tmp_path, content):
    """Write ``content`` as the workspace .env under ``tmp_path`` and load it."""
    (tmp_path / '.env').write_bytes(content)
    dot_env.load_dot_env(str(tmp_path))


def _ours(environ):
    """The variables of ``environ`` this suite owns (pytest itself sets others, mid-test)."""
    return {name: value for name, value in environ.items() if name.startswith(PREFIX)}


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


def test_invalid_utf8_skips_only_the_damaged_assignment_and_warns_once(tmp_path, capsys):
    prefix = f'{PREFIX}A=one\n{PREFIX}B=bad'.encode('utf-8')
    _load(tmp_path, prefix + b'\xffvalue\n' + f'{PREFIX}C=three\n'.encode('utf-8'))

    # The lines either side are applied exactly as written. The damaged one is left out
    # whole: a value with a replacement character in it is not what its author wrote,
    # and a credential read that way would be a different credential, not a damaged one.
    assert os.environ[PREFIX + 'A'] == 'one'
    assert PREFIX + 'B' not in os.environ
    assert os.environ[PREFIX + 'C'] == 'three'

    (line,) = _warnings(capsys)
    assert line.startswith('Warning: ')
    assert str(tmp_path / '.env') in line
    assert f'offset {len(prefix)}' in line
    assert 'line 2' in line
    assert '1 assignment line holding invalid bytes was skipped (first on line 2)' in line


def test_a_damaged_name_is_skipped_too(tmp_path, capsys):
    _load(tmp_path, f'{PREFIX}OK=1\n{PREFIX}BA'.encode('utf-8') + b'\xffD=2\n')

    assert os.environ[PREFIX + 'OK'] == '1'
    assert [name for name in os.environ if name.startswith(PREFIX)] == [PREFIX + 'OK']
    assert len(_warnings(capsys)) == 1


def test_a_damaged_comment_only_warns_and_changes_nothing(tmp_path, capsys):
    # A latin-1 comment is not an assignment, so no assignment is lost; the file is
    # still reported, once, because it is not UTF-8
    _load(tmp_path, f'# caf\xe9\n{PREFIX}A=1\n'.encode('latin-1'))

    assert os.environ[PREFIX + 'A'] == '1'
    (line,) = _warnings(capsys)
    assert 'not valid UTF-8' in line
    assert 'no assignment line is affected' in line


def test_an_encoded_replacement_character_is_valid_text_not_damage(tmp_path, capsys, any_text_environ):
    # U+FFFD written as the valid bytes EF BF BD is just a character in a value; only
    # a byte that is not valid UTF-8 marks a line as damaged
    value = '\N{REPLACEMENT CHARACTER}'
    _load(tmp_path, f'{PREFIX}A=x{value}y\n'.encode('utf-8'))

    assert any_text_environ[PREFIX + 'A'] == 'x' + value + 'y'
    assert _warnings(capsys) == []


def test_a_skipped_damaged_line_does_not_shadow_a_later_assignment(tmp_path, capsys):
    _load(tmp_path, f'{PREFIX}URI=https://prod\xff\n{PREFIX}URI=http://localhost\n'.encode('latin-1'))

    assert os.environ[PREFIX + 'URI'] == 'http://localhost'
    assert len(_warnings(capsys)) == 1


def test_offset_counts_the_byte_order_mark(tmp_path, capsys):
    raw = BOM + f'{PREFIX}A=1\n{PREFIX}B='.encode('utf-8') + b'\xff\n'
    _load(tmp_path, raw)

    invalid_at = raw.index(b'\xff')
    (line,) = _warnings(capsys)
    assert f'offset {invalid_at}' in line
    assert 'line 2' in line
    assert os.environ[PREFIX + 'A'] == '1'  # the mark is not part of the first name


def test_loading_never_modifies_the_file(tmp_path, capsys):
    path = tmp_path / '.env'
    content = f'{PREFIX}A=1\n{PREFIX}B=\xff\n{PREFIX}C=a\0b\n'.encode('latin-1')
    path.write_bytes(content)
    before = path.stat()

    dot_env.load_dot_env(str(tmp_path))

    assert path.read_bytes() == content
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert len(_warnings(capsys)) == 1


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
# load_dot_env - a name or value this process's environment cannot hold
#
# `ascii_filesystem` makes any platform behave like the engine's embedded interpreter
# on Linux, whose filesystem encoding is ASCII: os.environ raises UnicodeEncodeError for
# non-ASCII text. A real interpreter in that state is exercised further down.
# =========================================================================

ACUTE = '\N{LATIN SMALL LETTER E WITH ACUTE}'


def test_unstorable_value_is_skipped_with_one_warning(tmp_path, capsys, ascii_filesystem):
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B=caf{ACUTE}\n{PREFIX}C=3\n'.encode('utf-8'))

    assert _ours(ascii_filesystem) == {PREFIX + 'A': '1', PREFIX + 'C': '3'}
    (line,) = _warnings(capsys)
    assert line.startswith('Warning: ')
    assert '1 assignment line whose name or value this process cannot store' in line
    assert 'filesystem encoding ascii' in line
    assert 'was skipped (first on line 2)' in line
    assert ACUTE not in line  # no content of the file
    assert PREFIX not in line


def test_unstorable_name_is_skipped_with_one_warning(tmp_path, capsys, ascii_filesystem):
    _load(tmp_path, f'{PREFIX}{ACUTE}=1\n{PREFIX}A=2\n'.encode('utf-8'))

    assert _ours(ascii_filesystem) == {PREFIX + 'A': '2'}
    (line,) = _warnings(capsys)
    assert 'first on line 1' in line


def test_byte_order_mark_inside_a_value_is_unstorable_not_a_crash(tmp_path, capsys, ascii_filesystem):
    # What failed on CI: U+FEFF (and U+FFFD) cannot be encoded as ASCII
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B=\N{ZERO WIDTH NO-BREAK SPACE}2\n'.encode('utf-8'))

    assert _ours(ascii_filesystem) == {PREFIX + 'A': '1'}
    assert len(_warnings(capsys)) == 1


def test_a_skipped_unstorable_line_does_not_shadow_a_later_assignment(tmp_path, capsys, ascii_filesystem):
    _load(tmp_path, f'{PREFIX}URI=https://prod{ACUTE}\n{PREFIX}URI=http://localhost\n'.encode('utf-8'))

    assert _ours(ascii_filesystem) == {PREFIX + 'URI': 'http://localhost'}
    assert len(_warnings(capsys)) == 1


def test_real_environment_wins_before_storability_matters(tmp_path, capsys, ascii_filesystem):
    # The variable is already set, so the file's value is never even encoded: no skip, no warning
    ascii_filesystem[PREFIX + 'A'] = 'from-shell'
    _load(tmp_path, f'{PREFIX}A=caf{ACUTE}\n{PREFIX}B=2\n'.encode('utf-8'))

    assert _ours(ascii_filesystem) == {PREFIX + 'A': 'from-shell', PREFIX + 'B': '2'}
    assert _warnings(capsys) == []


def test_every_kind_of_damage_in_one_file_gives_one_line_and_keeps_the_valid_lines(tmp_path, capsys, ascii_filesystem):
    secret = 'sekret-token-4f9a'
    raw = f'{PREFIX}GOOD1=1\n{PREFIX}BAD=a\xffb{secret}\n{PREFIX}NUL=a\0b\n'.encode(
        'latin-1'
    ) + f'{PREFIX}ACUTE=caf{ACUTE}{secret}\n{PREFIX}GOOD2=2\n'.encode('utf-8')
    _load(tmp_path, raw)

    assert _ours(ascii_filesystem) == {PREFIX + 'GOOD1': '1', PREFIX + 'GOOD2': '2'}
    (line,) = _warnings(capsys)
    assert line.count('Warning:') == 1
    assert secret not in line
    assert PREFIX not in line
    assert len(line) < 600  # bounded: counts and positions, whatever the file holds


def test_many_bad_lines_still_give_one_short_warning(tmp_path, capsys, ascii_filesystem):
    _load(tmp_path, f'{PREFIX}X=1{ACUTE}\n'.encode('utf-8') * 5000 + b'\xff=1\n' * 5000)

    (line,) = _warnings(capsys)
    assert len(line) < 600


# =========================================================================
# UTF-8 byte-order mark (what Windows PowerShell 5's Set-Content -Encoding UTF8 writes)
# =========================================================================

BOM = b'\xef\xbb\xbf'


BOM_CHAR = '\N{ZERO WIDTH NO-BREAK SPACE}'


def test_leading_bom_is_not_part_of_the_first_name(tmp_path, capsys, any_text_environ):
    # printf '\xef\xbb\xbfRRTEST_DOTENV_BOM=http://x\nRRTEST_DOTENV_B=2\n' > .env
    _load(tmp_path, BOM + f'{PREFIX}BOM=http://x\n{PREFIX}B=2\n'.encode('utf-8'))

    assert _ours(any_text_environ) == {PREFIX + 'BOM': 'http://x', PREFIX + 'B': '2'}
    assert BOM_CHAR + PREFIX + 'BOM' not in any_text_environ
    assert _warnings(capsys) == []  # a BOM is valid UTF-8: no warning


def test_a_bom_inside_the_file_is_still_ordinary_text(tmp_path, any_text_environ):
    # Only a LEADING mark is skipped; one elsewhere belongs to its value
    _load(tmp_path, f'{PREFIX}A=1\n{PREFIX}B='.encode('utf-8') + BOM + b'2\n')
    assert any_text_environ[PREFIX + 'B'] == BOM_CHAR + '2'


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


@pytest.mark.parametrize(
    ('encoding', 'content', 'expected'),
    [
        # The byte-order mark makes line 1 invalid UTF-8 and the NULs make it a NUL line: one line, counted once
        (
            'utf-16',
            'X=1\n',
            'is not valid UTF-8 (first invalid byte at offset 0, on line 1); '
            'has 1 assignment line containing NUL characters, which was skipped (first on line 1; is the file UTF-16?)',
        ),
        (
            'utf-16',
            'A=1\nB=2\n',
            'is not valid UTF-8 (first invalid byte at offset 0, on line 1); '
            'has 2 assignment lines containing NUL characters, which were skipped (first on line 1; is the file UTF-16?)',
        ),
        (
            'utf-16-le',
            'A=1\nB=2\n',
            'has 2 assignment lines containing NUL characters, which were skipped (first on line 1; is the file UTF-16?)',
        ),
    ],
    ids=['bom-one-line', 'bom-two-lines', 'no-bom-two-lines'],
)
def test_utf16_warning_counts_each_skipped_line_once(tmp_path, capsys, encoding, content, expected):
    _load(tmp_path, content.encode(encoding))

    (line,) = _warnings(capsys)
    assert line == f'Warning: {tmp_path / ".env"} {expected}.'
    assert 'holding invalid bytes' not in line  # the same line is not also "invalid"


def test_each_kind_of_skipped_line_is_counted_under_one_reason(tmp_path, capsys):
    # line 1 invalid bytes only, line 2 NUL only, line 3 both
    _load(tmp_path, b'A=\xff\nB=a\0b\n\xffC=1\0\nD=ok\n')

    (line,) = _warnings(capsys)
    assert os.environ['D'] == 'ok'
    assert '1 assignment line holding invalid bytes was skipped (first on line 1)' in line
    assert '2 assignment lines containing NUL characters, which were skipped (first on line 2' in line


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
    assert message.endswith('Fix or remove it, then run the command again.')  # here the file is what is wrong
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
    path.write_bytes(
        b'# keep me\nROCKETRIDE_DEPLOY_URI=https://prod.example\nROCKETRIDE_URI=http://old\n\nOTHER=1\n',
    )
    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    assert path.read_bytes() == (
        b'# keep me\nROCKETRIDE_DEPLOY_URI=https://prod.example\nROCKETRIDE_URI=http://dev\n\nOTHER=1\nROCKETRIDE_APIKEY=k\n'
    )


@pytest.mark.parametrize('ending', [b'\n', b'\r\n', b'\r'], ids=['lf', 'crlf', 'cr'])
def test_write_keeps_the_files_own_line_ending(tmp_path, ending):
    # Not the platform's: Windows must not turn LF into CRLF and POSIX must not turn CRLF into LF.
    # Bytes in, bytes out - the rewritten line, the appended line and every other line.
    path = tmp_path / '.env'
    lines = [b'# keep me', b'ROCKETRIDE_URI=http://old', b'', b'OTHER=1']
    path.write_bytes(ending.join(lines) + ending)

    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    expected = [b'# keep me', b'ROCKETRIDE_URI=http://dev', b'', b'OTHER=1', b'ROCKETRIDE_APIKEY=k']
    assert path.read_bytes() == ending.join(expected) + ending


def test_write_keeps_mixed_line_endings_line_by_line(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'A=1\r\nROCKETRIDE_URI=http://old\nB=2\rC=3\r\n')

    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    # untouched lines keep their own ending; the new line takes the file's first one
    assert path.read_bytes() == b'A=1\r\nROCKETRIDE_URI=http://dev\nB=2\rC=3\r\nROCKETRIDE_APIKEY=k\r\n'


def test_write_ends_an_unterminated_last_line_the_way_the_file_does(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'A=1\r\nROCKETRIDE_URI=http://old')

    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev'}, str(tmp_path))

    assert path.read_bytes() == b'A=1\r\nROCKETRIDE_URI=http://dev\r\n'


def test_write_creates_a_new_file_with_lf_on_every_platform(tmp_path):
    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev', 'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    assert (tmp_path / '.env').read_bytes() == b'ROCKETRIDE_URI=http://dev\nROCKETRIDE_APIKEY=k\n'


def test_write_appends_next_to_the_last_assignment_not_after_trailing_blank_lines(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'A=1\r\n\r\n\r\n')

    dot_env.write_dot_env({'ROCKETRIDE_APIKEY': 'k'}, str(tmp_path))

    assert path.read_bytes() == b'A=1\r\nROCKETRIDE_APIKEY=k\r\n'


def test_write_does_not_cut_a_line_at_a_separator_the_reader_ignores(tmp_path):
    # str.splitlines() also splits at form feed and U+2028; the reader does not, so a value
    # holding either is ONE line and must survive a rewrite of another line byte for byte
    path = tmp_path / '.env'
    other = 'NOTE=a\x0cb\N{LINE SEPARATOR}c\x1dd\x85e'.encode('utf-8')
    path.write_bytes(other + b'\nROCKETRIDE_URI=http://old\n')

    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev'}, str(tmp_path))

    assert path.read_bytes() == other + b'\nROCKETRIDE_URI=http://dev\n'


def test_write_refuses_a_connection_value_this_process_cannot_store(tmp_path, ascii_filesystem):
    # The reader skipped this line, so a caller deciding from what the reader saw (is the
    # deploy pair pointing elsewhere?) would be deciding blind: the writer refuses instead
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    content = f'ROCKETRIDE_DEPLOY_URI=https://prod.example/caf{acute}\nOTHER=1\n'.encode('utf-8')
    path = tmp_path / '.env'
    path.write_bytes(content)

    for call in (dot_env.check_dot_env_writable, lambda cwd: dot_env.write_dot_env({'ROCKETRIDE_URI': 'x'}, cwd)):
        with pytest.raises(dot_env.DotEnvError) as error:
            call(str(tmp_path))
        message = str(error.value)
        assert 'cannot store' in message
        assert 'filesystem encoding ascii' in message
        assert 'on line 1' in message
        assert acute not in message and 'prod.example' not in message
        assert '\n' not in message
        # The file is fine; the process is the limit, and the message says what helps
        assert 'Nothing is wrong with the file' in message
        assert 'UTF-8 locale' in message and 'LC_ALL=C.UTF-8' in message
        assert 'Fix or remove it' not in message
    assert path.read_bytes() == content


def test_write_leaves_an_unrelated_line_it_cannot_store_alone(tmp_path, ascii_filesystem):
    # The writer owns only the keys it is given; a non-ASCII line it does not own is not its
    # concern, and costs `login` nothing on an ASCII-encoded process
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    path = tmp_path / '.env'
    path.write_bytes(f'NOTE=caf{acute}\nROCKETRIDE_URI=http://old\n'.encode('utf-8'))

    dot_env.check_dot_env_writable(str(tmp_path))
    dot_env.write_dot_env({'ROCKETRIDE_URI': 'http://dev'}, str(tmp_path))

    assert path.read_bytes() == f'NOTE=caf{acute}\nROCKETRIDE_URI=http://dev\n'.encode('utf-8')


def test_write_accepts_non_ascii_text_when_the_process_can_store_it(tmp_path, monkeypatch):
    # The control: the same kind of file is fine where the filesystem encoding can hold it
    monkeypatch.setattr(os, 'fsencode', lambda value: value.encode('utf-8', 'surrogateescape'))
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    path = tmp_path / '.env'
    path.write_bytes(f'NOTE=caf{acute}\n'.encode('utf-8'))

    dot_env.write_dot_env({'A': '1'}, str(tmp_path))

    assert path.read_bytes() == f'NOTE=caf{acute}\nA=1\n'.encode('utf-8')


# =========================================================================
# CLI start-up boundary (no engine)
# =========================================================================


def _command(tmp_path, argv, env_content=b'', extra_env=None):
    """
    Run the real CLI entry point in ``tmp_path`` with ``env_content`` as its .env.

    The child's environment carries no ``ROCKETRIDE_*`` variable (``extra_env`` adds to it). The arguments reach ``main()``
    through ``sys.argv`` set inside the child, not on its command line. When ``sys.executable`` is
    the engine's embedded interpreter (how CI runs this suite, on every platform) the engine's own
    parser consumes ``--pipeline``, ``--args``, ``--trace`` and ``--stream`` (bare or with
    ``=value``) from the command line before Python sees it, so ``start --pipeline no-such.pipe``
    arrives as ``start no-such.pipe`` and argparse rejects it with exit 2. Set from inside, argv
    is exactly what the test wrote, whichever interpreter runs it.
    """
    if env_content is not None:
        (tmp_path / '.env').write_bytes(env_content)
    env = {key: value for key, value in os.environ.items() if not key.startswith('ROCKETRIDE_')}
    env.update(extra_env or {})
    # Both source roots go onto sys.path INSIDE the child: in CI sys.executable is
    # the engine's isolated interpreter, which ignores PYTHONPATH.
    roots = [
        str(Path(rocketride.__file__).resolve().parents[1]),
        str(Path(rocketride_common.__file__).resolve().parents[1]),
    ]
    code = (
        f'import sys; sys.path[:0] = {roots!r}; sys.argv = {["rocketride", *argv]!r}; '
        'from rocketride.cli.main import main; main()'
    )
    return subprocess.run(
        [sys.executable, '-c', code],
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
#
# `start` is given `--pipeline` as a user types it: _command hands argv to main() from
# inside the child, past the engine's own option parser (see _command).
_PIPELINE_MISSING = 'Pipeline file not found: no-such.pipe'
_AFFECTED_COMMANDS = [
    pytest.param(['list', '--help'], 0, 'usage:', id='list'),
    pytest.param(['validate', 'no-such.pipe'], 2, 'File not found', id='validate'),
    pytest.param(['start', '--pipeline', 'no-such.pipe', '--apikey', 'k'], 1, _PIPELINE_MISSING, id='start'),
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
    assert 'unrecognized arguments' not in result.stderr  # the command line reached the application intact
    assert result.returncode == code, result.stderr
    assert marker in result.stdout + result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.startswith('Warning: ')]
    assert len(warnings) == 1
    assert str(tmp_path / '.env') in warnings[0]


def test_the_valid_lines_of_a_damaged_env_reach_the_command(tmp_path):
    # The pipeline and key come from valid lines of the file and the bad line sits between
    # them: `start` gets as far as reading the missing pipeline, which it only names if
    # the .env line was applied in the real process (no engine needed)
    content = b'ROCKETRIDE_PIPELINE=no-such.pipe\nX=\xff\nROCKETRIDE_APIKEY=k\n'
    result = _command(tmp_path, ['start'], content)

    assert 'Traceback' not in result.stderr
    assert result.returncode == 1, result.stderr
    assert _PIPELINE_MISSING in result.stdout + result.stderr
    assert len([line for line in result.stderr.splitlines() if line.startswith('Warning: ')]) == 1


def test_a_text_the_environment_cannot_hold_does_not_crash_the_command_or_cost_valid_lines(tmp_path):
    # A real interpreter, in a C locale with no UTF-8 coercion where it can be asked for
    # (on Linux; the engine's embedded interpreter is ASCII there whatever it is told):
    # non-ASCII text in a value cannot be stored when the filesystem encoding is ASCII,
    # and is stored otherwise. Either way: no crash, the valid lines are applied, one warning
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    content = f'{PREFIX}A=1\n{PREFIX}B=caf{acute}\n{PREFIX}C=3\n'.encode('utf-8') + f'{PREFIX}D=\xff\n'.encode(
        'latin-1'
    )
    roots = [
        str(Path(rocketride.__file__).resolve().parents[1]),
        str(Path(rocketride_common.__file__).resolve().parents[1]),
    ]
    probe = (
        'import json, os, sys; '
        f'sys.path[:0] = {roots!r}; '
        'from rocketride_common.env import load_dot_env; load_dot_env(); '
        'print(json.dumps({"encoding": sys.getfilesystemencoding(), '
        f'"env": {{k: v for k, v in os.environ.items() if k.startswith({PREFIX!r})}}}}))'
    )
    (tmp_path / '.env').write_bytes(content)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('ROCKETRIDE_', PREFIX))}
    env.update({'LC_ALL': 'C', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'})
    result = subprocess.run(
        [sys.executable, '-c', probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    ascii_only = report['encoding'].lower().replace('_', '-') in ('ascii', 'us-ascii', 'ansi-x3.4-1968')
    expected = {PREFIX + 'A': '1', PREFIX + 'C': '3'}
    if not ascii_only:
        expected[PREFIX + 'B'] = 'caf' + acute
    assert report['env'] == expected
    assert 'Traceback' not in result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.startswith('Warning: ')]
    assert len(warnings) == 1
    assert ('cannot store' in warnings[0]) == ascii_only


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


def _login(tmp_path, monkeypatch, capsys, env_content, deploy_pair=False):
    """Run `rocketride login` (`--deploy` with ``deploy_pair``) against a stubbed server with ``env_content`` as the .env."""
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
    args = SimpleNamespace(uri='http://dev.example', apikey='dev-key', json=None, deploy=True, deploy_pair=deploy_pair)
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


def test_login_leaves_a_prod_deploy_line_alone_when_this_process_cannot_store_it(
    tmp_path, monkeypatch, capsys, ascii_filesystem
):
    # The loader skips the deploy line on an ASCII-encoded process, so os.environ shows no deploy
    # target and `login` would mirror the dev pair over it: it must refuse instead
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    content = f'ROCKETRIDE_DEPLOY_URI=https://prod.example/caf{acute}\nNOTE=1\n'.encode('utf-8')
    code, contacted, captured = _login(tmp_path, monkeypatch, capsys, content)

    assert code == 1
    assert (tmp_path / '.env').read_bytes() == content
    assert 'Refusing to update' in captured.err
    assert 'prod.example' not in captured.err
    assert contacted == []


@pytest.mark.parametrize('deploy_pair', [False, True], ids=['login', 'login-deploy'])
def test_login_never_rewrites_or_duplicates_a_deploy_line_it_could_not_see(
    tmp_path, monkeypatch, capsys, ascii_filesystem, deploy_pair
):
    # os.environ shows no deploy pair (the loader skipped the line), yet the file has one: a
    # login that went on would mirror the dev pair over it or append a second, unread line
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    content = (
        f'# deploy target\nROCKETRIDE_DEPLOY_URI=https://prod.example/caf{acute}\nROCKETRIDE_DEPLOY_APIKEY=prod-key\n'
    ).encode('utf-8')
    code, contacted, captured = _login(tmp_path, monkeypatch, capsys, content, deploy_pair=deploy_pair)

    assert 'ROCKETRIDE_DEPLOY_URI' not in ascii_filesystem  # what login saw
    assert code == 1
    assert (tmp_path / '.env').read_bytes() == content  # not one byte of it
    assert 'Refusing to update' in captured.err
    assert 'prod-key' not in captured.err and 'prod.example' not in captured.err
    assert contacted == []


def test_login_cli_never_rewrites_a_deploy_line_in_an_ascii_encoded_process(tmp_path):
    # The same, through the real entry point in a process whose filesystem encoding is ASCII where the
    # platform lets it be (Linux; the engine's interpreter is ASCII there whatever it is told). Where it
    # cannot be, the line loads, `login` fails to reach the unroutable server, and the file is still untouched.
    acute = '\N{LATIN SMALL LETTER E WITH ACUTE}'
    content = f'ROCKETRIDE_DEPLOY_URI=https://prod.example/caf{acute}\nROCKETRIDE_DEPLOY_APIKEY=prod-key\n'.encode(
        'utf-8'
    )
    ascii_env = {'LC_ALL': 'C', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'}
    encoding = subprocess.run(
        [sys.executable, '-c', 'import sys; print(sys.getfilesystemencoding())'],
        env={**{k: v for k, v in os.environ.items() if not k.startswith('ROCKETRIDE_')}, **ascii_env},
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()
    is_ascii = encoding.lower().replace('_', '-') in ('ascii', 'us-ascii', 'ansi-x3.4-1968')

    result = _command(tmp_path, ['login', '--uri', 'http://127.0.0.1:1', '--apikey', 'k'], content, ascii_env)

    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert (tmp_path / '.env').read_bytes() == content
    assert ('Refusing to update' in result.stderr) == is_ascii
    assert 'prod-key' not in result.stderr and 'prod.example' not in result.stderr


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
