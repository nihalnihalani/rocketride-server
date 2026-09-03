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

"""Tests for the git ref resolver used by ``rocketride diff --git``.

Most cases stub ``subprocess.run`` so no real git or repository is needed; a
single, git-gated integration test exercises the real ``git show`` plumbing in
an isolated temporary repository.
"""

import json
import shutil
import subprocess

import pytest

from rocketride.pipediff import PipeDiffError, gitref, resolve_git_ref

SAMPLE_PIPE = {
    'components': [{'id': 'a', 'provider': 'src', 'config': {}}],
    'version': 1,
}


def _completed(returncode, stdout='', stderr=''):
    """Build a stub ``CompletedProcess`` result."""
    return subprocess.CompletedProcess(args=['git'], returncode=returncode, stdout=stdout, stderr=stderr)


def _install_fake_git(monkeypatch, responses):
    """Patch ``subprocess.run`` in gitref to reply per git subcommand.

    ``responses`` maps the subcommand ("rev-parse" or "show") to either a
    ``CompletedProcess`` or an ``Exception`` instance (which is raised).
    """

    def fake_run(args, **_kwargs):
        subcommand = args[3]  # ['git', '-C', <dir>, <subcommand>, ...]
        outcome = responses[subcommand]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(gitref.subprocess, 'run', fake_run)


# ---------------------------------------------------------------------------
# Mocked subprocess cases
# ---------------------------------------------------------------------------


def test_resolve_returns_parsed_pipe_when_found(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout=json.dumps(SAMPLE_PIPE)),
        },
    )
    assert resolve_git_ref('HEAD', '/repo/pipeline.pipe') == SAMPLE_PIPE


@pytest.mark.parametrize(
    'stderr',
    [
        "fatal: path 'pipeline.pipe' exists on disk, but not in 'HEAD'",
        "fatal: path 'pipeline.pipe' does not exist in 'HEAD'",
    ],
)
def test_resolve_returns_none_when_path_absent_in_ref(monkeypatch, stderr):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(128, stderr=stderr),
        },
    )
    assert resolve_git_ref('HEAD', '/repo/pipeline.pipe') is None


def test_resolve_raises_on_unknown_ref(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(128, stderr="fatal: invalid object name 'nope'."),
        },
    )
    with pytest.raises(PipeDiffError, match='git show'):
        resolve_git_ref('nope', '/repo/pipeline.pipe')


def test_resolve_raises_when_not_a_git_repo(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(128, stderr='fatal: not a git repository (or any parent up to /)'),
        },
    )
    with pytest.raises(PipeDiffError, match='Not a git repository'):
        resolve_git_ref('HEAD', '/tmp/pipeline.pipe')


def test_resolve_raises_when_git_missing(monkeypatch):
    _install_fake_git(monkeypatch, {'rev-parse': FileNotFoundError('git')})
    with pytest.raises(PipeDiffError, match='git executable not found'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


def test_resolve_raises_on_timeout(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {'rev-parse': subprocess.TimeoutExpired(cmd='git', timeout=30)},
    )
    with pytest.raises(PipeDiffError, match='timed out'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


def test_resolve_raises_on_undecodable_git_output(monkeypatch):
    # subprocess.run(text=True, encoding='utf-8') raises UnicodeDecodeError when a
    # blob is not UTF-8 text; that is a ValueError, so without a handler it left
    # the pipediff API as a raw traceback instead of a PipeDiffError.
    _install_fake_git(
        monkeypatch,
        {'rev-parse': UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')},
    )
    with pytest.raises(PipeDiffError, match='not valid UTF-8'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


def test_resolve_raises_on_undecodable_show_output(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte'),
        },
    )
    with pytest.raises(PipeDiffError, match='not valid UTF-8'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


def test_resolve_raises_on_invalid_json_content(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout='{ not json'),
        },
    )
    with pytest.raises(PipeDiffError, match='Invalid JSON'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


def test_resolve_raises_when_ref_content_is_not_a_pipe(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout=json.dumps({'version': 1})),
        },
    )
    with pytest.raises(PipeDiffError, match="missing a 'components' list"):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


# ---------------------------------------------------------------------------
# Real git integration (isolated temp repo)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_resolve_git_ref_real_repository(tmp_path):
    def git(*args):
        result = subprocess.run(['git', *args], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result

    git('init', '-q')
    pipe_file = tmp_path / 'pipeline.pipe'
    pipe_file.write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    git('add', 'pipeline.pipe')
    git('-c', 'user.email=t@example.com', '-c', 'user.name=Tester', 'commit', '-q', '-m', 'init')

    # The committed content is returned from HEAD.
    assert resolve_git_ref('HEAD', str(pipe_file)) == SAMPLE_PIPE

    # Working-tree edits do not affect what HEAD reports.
    pipe_file.write_text(json.dumps({**SAMPLE_PIPE, 'version': 2}), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(pipe_file))['version'] == 1

    # A file never committed is absent from HEAD -> None (treated as all-added).
    untracked = tmp_path / 'untracked.pipe'
    untracked.write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(untracked)) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
