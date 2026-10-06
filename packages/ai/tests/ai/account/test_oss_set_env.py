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
import os
import sys
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values

from ai.account.oss import Account

SECRET = 'sentinel-set-env-value'
BROKER_URL = 'https://broker.example/provision'
BROKER_TOKEN = 'operator-broker-token'


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
    (tmp_path / '.env').write_text(
        'ROCKETRIDE_GX_KEEP=kept\n'
        '# operator settings\n'
        f'RR_DB_BROKER_URL={BROKER_URL}\n'
        f'RR_DB_BROKER_TOKEN={BROKER_TOKEN}\n',
        encoding='utf-8',
    )
    return tmp_path


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


def test_a_quoted_value_ending_in_a_backslash_is_refused(engine_dir):
    """Such a value needs quotes in the file, and older python-dotenv releases
    read a backslash before the closing quote as an escaped quote.
    """
    message = _assert_refused(engine_dir, {'ROCKETRIDE_GX_KEEP': 'kept', 'ROCKETRIDE_GX_VALUE': f' {SECRET}\\'})
    assert 'ROCKETRIDE_GX_VALUE' in message


@pytest.mark.parametrize('env', [{'ROCKETRIDE_GX_VALUE': 5}, {'ROCKETRIDE_GX_VALUE': None}, ['ROCKETRIDE_GX_VALUE']])
def test_a_non_string_value_or_a_non_object_env_is_refused(engine_dir, env):
    _assert_refused(engine_dir, env)


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
