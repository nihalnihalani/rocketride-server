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
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pipediff_git_helpers
from pipediff_git_helpers import init_repo, isolate_git_environment

from rocketride.pipediff import PipeDiffError, gitref, resolve_git_ref

SAMPLE_PIPE = {
    'components': [{'id': 'a', 'provider': 'src', 'config': {}}],
    'version': 1,
}


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch):
    # The code under test runs git too: keep it away from the developer's git
    # configuration, hooks and signing settings, and from inherited GIT_* variables.
    isolate_git_environment(monkeypatch)


def _completed(returncode, stdout='', stderr=''):
    """Build a stub ``CompletedProcess`` result."""
    return subprocess.CompletedProcess(args=['git'], returncode=returncode, stdout=stdout, stderr=stderr)


def _fake_ls_tree(args, tree):
    """Answer ``git ls-tree -z <ref>:<dir>`` from ``tree`` ({committed path: mode})."""
    directory = args[-1].partition(':')[2]
    prefix = f'{directory}/' if directory else ''
    entries = {}
    for path, mode in tree.items():
        if path.startswith(prefix):
            head, slash, _rest = path[len(prefix) :].partition('/')
            entries[head] = '040000 tree' if slash else f'{mode} blob'
    stdout = ''.join(f'{meta} deadbeef\t{name}\0' for name, meta in entries.items())
    return _completed(0, stdout=stdout)


def _install_fake_git(monkeypatch, responses, tree=None, links=None):
    """Patch ``subprocess.run`` in gitref to reply per git invocation.

    ``responses`` maps an invocation key to either a ``CompletedProcess`` or an
    ``Exception`` instance (which is raised). The keys are the git subcommand
    ("rev-parse", "cat-file", "ls-tree", "show"), plus "rev-parse-verify" for the
    ref verification (``rev-parse --verify``) as distinct from the
    repository-root lookup (``rev-parse --show-toplevel``). "rev-parse-verify"
    and "cat-file" default to success, so a test only has to name the step it
    cares about. "ls-tree" defaults to listing ``tree``, a map of committed
    path to git mode (default: a regular ``pipeline.pipe`` at the top), and
    "cat-file" reads the link text of a committed symlink from ``links``, a map
    of committed path to the text stored there.
    """
    committed = {'pipeline.pipe': '100644'} if tree is None else tree
    defaults = {
        'rev-parse-verify': _completed(0, stdout='deadbeef\n'),
        'cat-file': _completed(0),
    }

    def fake_run(args, **_kwargs):
        subcommand = args[3]  # ['git', '-C', <dir>, <subcommand>, ...]
        key = 'rev-parse-verify' if subcommand == 'rev-parse' and '--verify' in args else subcommand
        if key in responses:
            outcome = responses[key]
        elif key == 'ls-tree':
            outcome = _fake_ls_tree(args, committed)
        elif key == 'cat-file' and links is not None:
            outcome = _completed(0, stdout=links[args[-1].partition(':')[2]])
        else:
            outcome = defaults[key]
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
        '',
    ],
)
def test_resolve_returns_none_when_path_absent_in_ref(monkeypatch, stderr):
    # The verdict comes from the tree listing (exit 0, entry missing), whatever git prints.
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'ls-tree': _completed(0, stderr=stderr),
        },
    )
    assert resolve_git_ref('HEAD', '/repo/pipeline.pipe') is None


def test_resolve_raises_on_unknown_ref(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'rev-parse-verify': _completed(128, stderr='fatal: Needed a single revision'),
        },
    )
    with pytest.raises(PipeDiffError, match='Unknown git ref'):
        resolve_git_ref('nope', '/repo/pipeline.pipe')


def test_resolve_raises_when_bad_ref_name_echoes_a_path_absent_phrase(monkeypatch):
    """A bad ref must stay an error even when git's diagnostic quotes it.

    git echoes the offending revision back, so a ref whose *name* contains
    "does not exist in" used to be mistaken for "the file is not in this ref" and
    silently produced an all-added diff instead of exit code 2.
    """
    bad_ref = 'nope does not exist in'
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'rev-parse-verify': _completed(128, stderr=f"fatal: invalid object name '{bad_ref}'."),
        },
    )
    with pytest.raises(PipeDiffError, match='Unknown git ref'):
        resolve_git_ref(bad_ref, '/repo/pipeline.pipe')


def test_resolve_raises_when_show_fails_for_a_present_object(monkeypatch):
    """A verified ref plus a present object that still fails to read is an error."""
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(128, stderr='fatal: unable to read object'),
        },
    )
    with pytest.raises(PipeDiffError, match='git show'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


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


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity', '1e309', '-1e309', '1e-400', '-1e-400'])
def test_resolve_rejects_unsupported_numeric_content_with_git_context(monkeypatch, literal):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout='{"components": [{"id": "a", "config": {"value": ' + literal + '}}]}'),
        },
    )
    with pytest.raises(PipeDiffError, match='Invalid JSON') as error:
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')
    assert 'HEAD:pipeline.pipe' in str(error.value)
    assert literal in str(error.value)


def test_resolve_preserves_context_for_numeric_validation_of_historical_metadata(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout='{"components": [], "project_id": 1e309}'),
        },
    )
    with pytest.raises(PipeDiffError, match='HEAD:pipeline.pipe'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


@pytest.mark.parametrize('literal', ['0e9999', '-0e-9999', '5e-324', '-5e-324', '1.7976931348623157e308'])
def test_resolve_accepts_supported_finite_numeric_content(monkeypatch, literal):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout='{"components": [{"id": "a", "config": {"value": ' + literal + '}}]}'),
        },
    )
    pipe = resolve_git_ref('HEAD', '/repo/pipeline.pipe')
    assert pipe['components'][0]['config']['value'] == float(literal)
    json.dumps(pipe, allow_nan=False)


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
# Mocked symlink walk (the tree is described, not built)
# ---------------------------------------------------------------------------

_LINK = '120000'


def _resolve_walk(monkeypatch, path, tree, links):
    """Resolve ``path`` against a described tree and report the blob that was read."""
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'show': _completed(0, stdout=json.dumps(SAMPLE_PIPE)),
        },
        tree=tree,
        links=links,
    )
    shown = []
    real_run = gitref.subprocess.run

    def spy(args, **kwargs):
        if args[3] == 'show':
            shown.append(args[-1])
        return real_run(args, **kwargs)

    monkeypatch.setattr(gitref.subprocess, 'run', spy)
    pipe = resolve_git_ref('HEAD', path)
    return pipe, shown


def test_walk_follows_a_file_link_chain_as_committed(monkeypatch):
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/current.pipe',
        {'current.pipe': _LINK, 'mid.pipe': _LINK, 'v1.pipe': '100644'},
        {'current.pipe': 'mid.pipe', 'mid.pipe': 'v1.pipe'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:v1.pipe']


def test_walk_follows_a_directory_link_in_the_requested_path(monkeypatch):
    # `flows` is a link at the ref: git cannot list through it, so the link text
    # has to be substituted for the component
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/flows/rag.pipe',
        {'flows': _LINK, 'flows_v1/rag.pipe': '100644', 'flows_v2/rag.pipe': '100644'},
        {'flows': 'flows_v1'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:flows_v1/rag.pipe']


def test_walk_follows_a_link_whose_target_runs_through_a_directory_link(monkeypatch):
    # current.pipe -> lnk/v.pipe with lnk -> real: `cat-file -e HEAD:lnk/v.pipe`
    # fails, and treating that as "absent" reported the whole file as added
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/current.pipe',
        {'current.pipe': _LINK, 'lnk': _LINK, 'real/v.pipe': '100644'},
        {'current.pipe': 'lnk/v.pipe', 'lnk': 'real'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:real/v.pipe']


def test_walk_applies_dotdot_in_link_text_to_the_resolved_path(monkeypatch):
    # lnk -> deep/sub, so `lnk/..` is deep/, not the directory holding the link
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/current.pipe',
        {'current.pipe': _LINK, 'lnk': _LINK, 'x.pipe': '100644', 'deep/x.pipe': '100644', 'deep/sub/y.pipe': '100644'},
        {'current.pipe': 'lnk/../x.pipe', 'lnk': 'deep/sub'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:deep/x.pipe']


def test_walk_lets_dotdot_climb_back_to_the_repository_root_but_not_past_it(monkeypatch):
    # lnk -> deep/sub: `lnk/../..` is the repository root, which is still inside
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/current.pipe',
        {'current.pipe': _LINK, 'lnk': _LINK, 'x.pipe': '100644', 'deep/sub/y.pipe': '100644'},
        {'current.pipe': 'lnk/../../x.pipe', 'lnk': 'deep/sub'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:x.pipe']


def test_walk_resolves_link_text_relative_to_the_directory_holding_the_link(monkeypatch):
    pipe, shown = _resolve_walk(
        monkeypatch,
        '/repo/a/b/current.pipe',
        {'a/b/current.pipe': _LINK, 'a/v.pipe': '100644', 'v.pipe': '100644'},
        {'a/b/current.pipe': '../v.pipe'},
    )
    assert pipe == SAMPLE_PIPE
    assert shown == ['HEAD:a/v.pipe']


def test_walk_returns_none_when_a_link_target_is_absent_at_the_ref(monkeypatch):
    pipe, _shown = _resolve_walk(
        monkeypatch, '/repo/current.pipe', {'current.pipe': _LINK}, {'current.pipe': 'gone.pipe'}
    )
    assert pipe is None


def test_walk_returns_none_when_a_directory_on_the_path_is_absent(monkeypatch):
    pipe, _shown = _resolve_walk(monkeypatch, '/repo/missing/rag.pipe', {'other/rag.pipe': '100644'}, {})
    assert pipe is None


@pytest.mark.parametrize(
    'target',
    ['/etc/rag.pipe', '../outside.pipe', 'lnk/../../../outside.pipe'],
    ids=['absolute', 'parent', 'through-a-link'],
)
def test_walk_rejects_a_link_that_leaves_the_repository(monkeypatch, target):
    with pytest.raises(PipeDiffError, match='outside the repository'):
        _resolve_walk(
            monkeypatch,
            '/repo/current.pipe',
            {'current.pipe': _LINK, 'lnk': _LINK, 'deep/sub/y.pipe': '100644'},
            {'current.pipe': target, 'lnk': 'deep/sub'},
        )


@pytest.mark.parametrize(
    ('tree', 'links'),
    [
        ({'a.pipe': _LINK, 'b.pipe': _LINK}, {'a.pipe': 'b.pipe', 'b.pipe': 'a.pipe'}),
        ({'a.pipe': _LINK}, {'a.pipe': 'a.pipe'}),
        ({'d': _LINK}, {'d': 'd/d'}),
    ],
    ids=['two-cycle', 'self-link', 'self-nesting-directory'],
)
def test_walk_stops_a_link_loop_with_a_clear_error(monkeypatch, tree, links):
    with pytest.raises(PipeDiffError, match='too many levels of symbolic links'):
        _resolve_walk(monkeypatch, f'/repo/{next(iter(tree))}', tree, links)


def test_walk_does_not_swallow_a_failing_tree_listing(monkeypatch):
    _install_fake_git(
        monkeypatch,
        {
            'rev-parse': _completed(0, stdout='/repo\n'),
            'ls-tree': _completed(128, stderr='fatal: unable to read tree'),
        },
    )
    with pytest.raises(PipeDiffError, match='ls-tree'):
        resolve_git_ref('HEAD', '/repo/pipeline.pipe')


# ---------------------------------------------------------------------------
# Real git integration (isolated temp repo)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_resolve_git_ref_real_repository(tmp_path):
    pipe_file = tmp_path / 'pipeline.pipe'
    pipe_file.write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(tmp_path, 'pipeline.pipe')

    # The committed content is returned from HEAD.
    assert resolve_git_ref('HEAD', str(pipe_file)) == SAMPLE_PIPE

    # Working-tree edits do not affect what HEAD reports.
    pipe_file.write_text(json.dumps({**SAMPLE_PIPE, 'version': 2}), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(pipe_file))['version'] == 1

    # A file never committed is absent from HEAD -> None (treated as all-added).
    untracked = tmp_path / 'untracked.pipe'
    untracked.write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(untracked)) is None


def _case_insensitive(path):
    """Report whether the filesystem holding ``path`` folds case."""
    probe = path / 'CaseProbe.tmp'
    probe.write_text('x', encoding='utf-8')
    try:
        return (path / 'caseprobe.tmp').exists()
    finally:
        probe.unlink()


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_untracked_symlink_is_looked_up_by_its_own_path(tmp_path):
    # Documented as `git show <ref>:<FILE>`: a link that is not in the ref is new,
    # even when the file it points at is tracked.
    (tmp_path / 'pipeline.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(tmp_path, 'pipeline.pipe')
    (tmp_path / 'link.pipe').symlink_to('pipeline.pipe')
    assert resolve_git_ref('HEAD', str(tmp_path / 'link.pipe')) is None


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_tracked_symlink_resolves_to_its_target(tmp_path):
    # `git show` of a committed link returns the link text, not a pipe; compare
    # the target the working-tree link reads instead.
    (tmp_path / 'pipeline.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    (tmp_path / 'link.pipe').symlink_to('pipeline.pipe')
    init_repo(tmp_path, 'pipeline.pipe', 'link.pipe')
    (tmp_path / 'pipeline.pipe').write_text(json.dumps({**SAMPLE_PIPE, 'version': 2}), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(tmp_path / 'link.pipe')) == SAMPLE_PIPE


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_repository_reached_through_a_symlinked_directory(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'pipeline.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(real, 'pipeline.pipe')
    (tmp_path / 'alias').symlink_to(real, target_is_directory=True)
    assert resolve_git_ref('HEAD', str(tmp_path / 'alias' / 'pipeline.pipe')) == SAMPLE_PIPE


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_mis_cased_path_finds_the_tracked_file_on_a_case_insensitive_filesystem(tmp_path):
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    sub = tmp_path / 'Flows'
    sub.mkdir()
    (sub / 'rag.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(tmp_path, 'Flows/rag.pipe')
    # The working-tree path opens the tracked file, so compare against it rather
    # than reporting every node as added.
    assert resolve_git_ref('HEAD', str(sub / 'RAG.pipe')) == SAMPLE_PIPE


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_mis_cased_path_to_a_tracked_symlink_compares_its_target(tmp_path):
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    (tmp_path / 'pipeline.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    (tmp_path / 'Link.pipe').symlink_to('pipeline.pipe')
    init_repo(tmp_path, 'pipeline.pipe', 'Link.pipe')
    (tmp_path / 'pipeline.pipe').write_text(json.dumps({**SAMPLE_PIPE, 'version': 2}), encoding='utf-8')
    # Case recovery finds the tracked link; its target is compared, not its text.
    assert resolve_git_ref('HEAD', str(tmp_path / 'link.pipe')) == SAMPLE_PIPE


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_differently_cased_new_file_is_new_on_a_case_sensitive_filesystem(tmp_path):
    if _case_insensitive(tmp_path):
        pytest.skip('filesystem folds case')
    (tmp_path / 'rag.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(tmp_path, 'rag.pipe')
    (tmp_path / 'RAG.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(tmp_path / 'RAG.pipe')) is None


def _pipe_with(value):
    return {'components': [{'id': 'a', 'provider': 'src', 'config': {'value': value}}], 'version': 1}


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_retargeted_symlink_compares_the_target_it_had_at_the_ref(tmp_path):
    # The old side follows the link text stored at the ref, not the link's
    # current target: a retarget from v1 to v2 is a real pipeline swap.
    (tmp_path / 'v1.pipe').write_text(json.dumps(_pipe_with(1)), encoding='utf-8')
    (tmp_path / 'v2.pipe').write_text(json.dumps(_pipe_with(2)), encoding='utf-8')
    (tmp_path / 'current.pipe').symlink_to('v1.pipe')
    init_repo(tmp_path, 'v1.pipe', 'v2.pipe', 'current.pipe')
    (tmp_path / 'current.pipe').unlink()
    (tmp_path / 'current.pipe').symlink_to('v2.pipe')
    assert resolve_git_ref('HEAD', str(tmp_path / 'current.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_symlink_at_the_ref_is_followed_even_when_the_file_is_now_regular(tmp_path):
    (tmp_path / 'v1.pipe').write_text(json.dumps(_pipe_with(1)), encoding='utf-8')
    (tmp_path / 'current.pipe').symlink_to('v1.pipe')
    init_repo(tmp_path, 'v1.pipe', 'current.pipe')
    (tmp_path / 'current.pipe').unlink()
    (tmp_path / 'current.pipe').write_text(json.dumps(_pipe_with(5)), encoding='utf-8')
    assert resolve_git_ref('HEAD', str(tmp_path / 'current.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_symlink_at_the_ref_pointing_outside_the_repository_is_an_error(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'current.pipe').symlink_to('../outside.pipe')
    init_repo(repo, 'current.pipe')
    (repo / 'current.pipe').unlink()
    (repo / 'current.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    with pytest.raises(PipeDiffError, match='outside the repository'):
        resolve_git_ref('HEAD', str(repo / 'current.pipe'))


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_dotdot_after_a_directory_symlink_follows_the_physical_path(tmp_path):
    # The blob looked up must be the file the OS opens for this path. On POSIX
    # `lnk/..` is the parent of lnk's target (deep/), not the directory holding
    # lnk; Windows folds `..` lexically first and opens the top-level x.pipe.
    (tmp_path / 'deep' / 'sub').mkdir(parents=True)
    (tmp_path / 'x.pipe').write_text(json.dumps(_pipe_with(1)), encoding='utf-8')
    (tmp_path / 'deep' / 'x.pipe').write_text(json.dumps(_pipe_with(7)), encoding='utf-8')
    (tmp_path / 'lnk').symlink_to('deep/sub', target_is_directory=True)
    init_repo(tmp_path, 'x.pipe', 'deep/x.pipe', 'lnk')
    path = str(tmp_path) + '/lnk/../x.pipe'
    with open(path, encoding='utf-8') as handle:
        opened = json.load(handle)
    assert resolve_git_ref('HEAD', path) == opened
    if os.name != 'nt':
        assert opened == _pipe_with(7)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.parametrize('spelling', ['RepoDir/flows/rag.pipe', 'repodir/Flows/rag.pipe', 'REPODIR/FLOWS/RAG.PIPE'])
def test_mis_cased_directories_find_the_tracked_file_on_a_case_insensitive_filesystem(tmp_path, spelling):
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    repo = tmp_path / 'RepoDir'
    (repo / 'Flows').mkdir(parents=True)
    (repo / 'Flows' / 'rag.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')
    init_repo(repo, 'Flows/rag.pipe')
    assert resolve_git_ref('HEAD', str(tmp_path / spelling)) == SAMPLE_PIPE


def _rename_case(path, new_name):
    """Rename ``path`` to ``new_name`` (same name, other case) the way a case-insensitive filesystem allows."""
    scratch = path.with_name('case-rename-scratch')
    os.rename(path, scratch)
    os.rename(scratch, path.with_name(new_name))


def _write_pipe(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_pipe_with(value)), encoding='utf-8')


def _read_pipe(path):
    return json.loads(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Directory links, `..` in link text, link loops (real git)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_retargeted_directory_symlink_compares_the_directory_it_had_at_the_ref(tmp_path):
    # `flows -> flows_v1` repointed to flows_v2 is the directory-level version of
    # the current.pipe retarget: the pipeline on disk is v2's, the old side must
    # be what flows/rag.pipe was at the ref (v1's), not flows_v2's copy at the ref
    _write_pipe(tmp_path / 'flows_v1' / 'rag.pipe', 1)
    _write_pipe(tmp_path / 'flows_v2' / 'rag.pipe', 2)
    (tmp_path / 'flows').symlink_to('flows_v1', target_is_directory=True)
    init_repo(tmp_path, 'flows_v1', 'flows_v2', 'flows')
    (tmp_path / 'flows').unlink()
    (tmp_path / 'flows').symlink_to('flows_v2', target_is_directory=True)

    path = tmp_path / 'flows' / 'rag.pipe'
    assert _read_pipe(path) == _pipe_with(2)
    assert resolve_git_ref('HEAD', str(path)) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_retargeted_directory_symlink_is_found_from_a_relative_path(tmp_path, monkeypatch):
    _write_pipe(tmp_path / 'flows_v1' / 'rag.pipe', 1)
    _write_pipe(tmp_path / 'flows_v2' / 'rag.pipe', 2)
    (tmp_path / 'flows').symlink_to('flows_v1', target_is_directory=True)
    init_repo(tmp_path, 'flows_v1', 'flows_v2', 'flows')
    (tmp_path / 'flows').unlink()
    (tmp_path / 'flows').symlink_to('flows_v2', target_is_directory=True)
    monkeypatch.chdir(tmp_path)

    assert resolve_git_ref('HEAD', os.path.join('flows', 'rag.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_directory_that_is_now_a_symlink_is_still_read_as_a_directory_at_the_ref(tmp_path):
    _write_pipe(tmp_path / 'flows' / 'rag.pipe', 1)
    _write_pipe(tmp_path / 'elsewhere' / 'rag.pipe', 2)
    init_repo(tmp_path, 'flows', 'elsewhere')
    shutil.rmtree(tmp_path / 'flows')
    (tmp_path / 'flows').symlink_to('elsewhere', target_is_directory=True)

    assert resolve_git_ref('HEAD', str(tmp_path / 'flows' / 'rag.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_link_through_a_directory_link_is_not_reported_as_new(tmp_path):
    # current.pipe -> lnk/v.pipe with lnk -> real: git trees do not traverse the
    # link, so `cat-file -e HEAD:lnk/v.pipe` fails; reading that as "absent"
    # reported an unchanged pipeline as one added node
    _write_pipe(tmp_path / 'real' / 'v.pipe', 1)
    (tmp_path / 'lnk').symlink_to('real', target_is_directory=True)
    (tmp_path / 'current.pipe').symlink_to('lnk/v.pipe')
    init_repo(tmp_path, 'real', 'lnk', 'current.pipe')

    assert _read_pipe(tmp_path / 'current.pipe') == _pipe_with(1)
    assert resolve_git_ref('HEAD', str(tmp_path / 'current.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.skipif(os.name == 'nt', reason='Windows does not resolve `..` in link text through a link the POSIX way')
def test_dotdot_in_committed_link_text_follows_the_physical_path(tmp_path):
    # current.pipe -> lnk/../x.pipe with lnk -> deep/sub: the OS opens deep/x.pipe
    # (the parent of lnk's TARGET); folding `..` as text read the top-level x.pipe
    _write_pipe(tmp_path / 'x.pipe', 2)
    _write_pipe(tmp_path / 'deep' / 'x.pipe', 1)
    # git records no empty directory, so deep/sub must hold a tracked file to exist at the ref
    _write_pipe(tmp_path / 'deep' / 'sub' / 'y.pipe', 3)
    (tmp_path / 'lnk').symlink_to('deep/sub', target_is_directory=True)
    (tmp_path / 'current.pipe').symlink_to('lnk/../x.pipe')
    init_repo(tmp_path, 'x.pipe', 'deep', 'lnk', 'current.pipe')
    _write_pipe(tmp_path / 'deep' / 'x.pipe', 2)  # the edit the diff should see

    assert _read_pipe(tmp_path / 'current.pipe') == _pipe_with(2)
    assert resolve_git_ref('HEAD', str(tmp_path / 'current.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_file_that_is_now_a_symlink_is_still_read_as_a_file_at_the_ref(tmp_path):
    _write_pipe(tmp_path / 'current.pipe', 1)
    _write_pipe(tmp_path / 'other.pipe', 9)
    init_repo(tmp_path, 'current.pipe', 'other.pipe')
    (tmp_path / 'current.pipe').unlink()
    (tmp_path / 'current.pipe').symlink_to('other.pipe')

    assert resolve_git_ref('HEAD', str(tmp_path / 'current.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_dotdot_after_a_directory_symlink_in_a_relative_path(tmp_path, monkeypatch):
    (tmp_path / 'deep' / 'sub').mkdir(parents=True)
    _write_pipe(tmp_path / 'x.pipe', 1)
    _write_pipe(tmp_path / 'deep' / 'x.pipe', 7)
    (tmp_path / 'lnk').symlink_to('deep/sub', target_is_directory=True)
    init_repo(tmp_path, 'x.pipe', 'deep/x.pipe', 'lnk')
    monkeypatch.chdir(tmp_path)
    path = os.path.join('lnk', os.pardir, 'x.pipe')

    opened = _read_pipe(Path(path))
    assert resolve_git_ref('HEAD', path) == opened
    if os.name != 'nt':
        assert opened == _pipe_with(7)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_symlink_loop_at_the_ref_is_a_clear_error(tmp_path):
    (tmp_path / 'a.pipe').symlink_to('b.pipe')
    (tmp_path / 'b.pipe').symlink_to('a.pipe')
    init_repo(tmp_path, 'a.pipe', 'b.pipe')

    with pytest.raises(PipeDiffError, match='too many levels of symbolic links'):
        resolve_git_ref('HEAD', str(tmp_path / 'a.pipe'))


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_directory_link_whose_target_was_absent_at_the_ref_is_new(tmp_path):
    # At the ref `flows` was a link to a directory that did not exist; the
    # pipeline in the real `flows/` directory now is therefore new
    _write_pipe(tmp_path / 'keep.pipe', 1)
    (tmp_path / 'flows').symlink_to('gone', target_is_directory=True)
    init_repo(tmp_path, 'keep.pipe', 'flows')
    (tmp_path / 'flows').unlink()
    _write_pipe(tmp_path / 'flows' / 'rag.pipe', 2)

    assert resolve_git_ref('HEAD', str(tmp_path / 'flows' / 'rag.pipe')) is None


def _retargeted_directory_link_repo(tmp_path):
    """Commit `flows -> flows_v1` beside a tracked sub/, then repoint the link to flows_v2 on disk."""
    _write_pipe(tmp_path / 'flows_v1' / 'rag.pipe', 1)
    _write_pipe(tmp_path / 'flows_v2' / 'rag.pipe', 2)
    _write_pipe(tmp_path / 'sub' / 'keep.pipe', 3)
    (tmp_path / 'flows').symlink_to('flows_v1', target_is_directory=True)
    init_repo(tmp_path, 'flows_v1', 'flows_v2', 'sub', 'flows')
    (tmp_path / 'flows').unlink()
    (tmp_path / 'flows').symlink_to('flows_v2', target_is_directory=True)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_directory_link_retarget_is_seen_through_dotdot_after_a_real_directory(tmp_path, monkeypatch):
    # `sub/../flows/rag.pipe` is `flows/rag.pipe`: the verdict must not depend on how
    # the same file is spelled, nor on the working directory
    _retargeted_directory_link_repo(tmp_path)

    assert resolve_git_ref('HEAD', str(tmp_path / 'sub' / '..' / 'flows' / 'rag.pipe')) == _pipe_with(1)
    monkeypatch.chdir(tmp_path / 'sub')
    assert resolve_git_ref('HEAD', os.path.join(os.pardir, 'flows', 'rag.pipe')) == _pipe_with(1)
    assert resolve_git_ref('HEAD', os.path.join('.', os.pardir, 'flows', '.', 'rag.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.parametrize('directory', ['d[1]', ':(top)x', 'with space'], ids=['glob', 'pathspec-magic', 'space'])
@pytest.mark.skipif(os.name == 'nt', reason='Windows file names cannot hold ":", "[" patterns the same way')
def test_directory_names_that_look_like_patterns_are_taken_literally(tmp_path, directory):
    # `ls-tree -- ':(top)x/'` reads the name as pathspec magic; the listing is
    # requested as <ref>:<directory> so it is a plain path
    _write_pipe(tmp_path / directory / '*a?.pipe', 1)
    _write_pipe(tmp_path / 'other' / '*a?.pipe', 2)
    init_repo(tmp_path, directory, 'other')

    assert resolve_git_ref('HEAD', str(tmp_path / directory / '*a?.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_typed_component_after_a_link_keeps_its_case_recovery(tmp_path):
    # lnk -> Flows is committed; `lnk/RAG.pipe` types the file after the link in
    # another case, which is still the tracked Flows/rag.pipe on this filesystem
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    _write_pipe(tmp_path / 'Flows' / 'rag.pipe', 1)
    (tmp_path / 'lnk').symlink_to('Flows', target_is_directory=True)
    init_repo(tmp_path, 'Flows', 'lnk')

    assert resolve_git_ref('HEAD', str(tmp_path / 'lnk' / 'RAG.pipe')) == _pipe_with(1)
    assert resolve_git_ref('HEAD', str(tmp_path / 'LNK' / 'RAG.pipe')) == _pipe_with(1)


def test_walk_stops_at_a_file_with_more_path_after_it(monkeypatch):
    pipe, _shown = _resolve_walk(monkeypatch, '/repo/pipeline.pipe/more.pipe', {'pipeline.pipe': '100644'}, {})
    assert pipe is None


# ---------------------------------------------------------------------------
# Case: every component is recovered from the ref's tree
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.parametrize(
    ('tracked', 'renamed_to', 'typed'),
    [
        ('Flows/rag.pipe', {'Flows': 'flows'}, 'flows/rag.pipe'),
        ('Flows/rag.pipe', {'Flows': 'flows'}, 'FLOWS/RAG.PIPE'),
        ('Outer/Flows/rag.pipe', {'Outer': 'outer', 'Outer/Flows': 'flows'}, 'outer/flows/rag.pipe'),
        ('Flows/rag.pipe', {'Flows/rag.pipe': 'RAG.pipe'}, 'Flows/rag.pipe'),
    ],
    ids=['directory', 'directory-typed-upper', 'two-directories', 'file'],
)
def test_case_only_rename_on_disk_still_finds_the_tracked_file(tmp_path, tracked, renamed_to, typed):
    # git status stays clean after a case-only rename on a case-insensitive
    # filesystem, so the file on disk IS the tracked file: nothing is "new"
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    _write_pipe(tmp_path / tracked, 1)
    init_repo(tmp_path, tracked.split('/')[0])
    for old, new in sorted(renamed_to.items(), key=lambda item: item[0].count('/'), reverse=True):
        _rename_case(tmp_path / old, new)

    assert resolve_git_ref('HEAD', str(tmp_path / typed)) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_tracked_link_is_followed_by_the_ref_even_when_it_is_now_a_regular_file_under_another_case(tmp_path):
    # The tree entry at the ref decides whether the content is a link, also after
    # the spelling was recovered: Link.pipe is a link there, a regular file now
    if not _case_insensitive(tmp_path):
        pytest.skip('filesystem is case-sensitive')
    _write_pipe(tmp_path / 'Flows' / 'v1.pipe', 1)
    (tmp_path / 'Flows' / 'Link.pipe').symlink_to('v1.pipe')
    init_repo(tmp_path, 'Flows')
    (tmp_path / 'Flows' / 'Link.pipe').unlink()
    _write_pipe(tmp_path / 'Flows' / 'Link.pipe', 5)

    assert resolve_git_ref('HEAD', str(tmp_path / 'flows' / 'link.pipe')) == _pipe_with(1)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_differently_cased_directory_is_new_on_a_case_sensitive_filesystem(tmp_path):
    if _case_insensitive(tmp_path):
        pytest.skip('filesystem folds case')
    _write_pipe(tmp_path / 'Flows' / 'rag.pipe', 1)
    init_repo(tmp_path, 'Flows')
    _write_pipe(tmp_path / 'flows' / 'rag.pipe', 2)  # a different, untracked directory

    assert resolve_git_ref('HEAD', str(tmp_path / 'flows' / 'rag.pipe')) is None
    assert resolve_git_ref('HEAD', str(tmp_path / 'Flows' / 'rag.pipe')) == _pipe_with(1)


# ---------------------------------------------------------------------------
# The fixtures themselves are hermetic (they run in CI and on developer machines)
# ---------------------------------------------------------------------------


def _hostile_user_setup(tmp_path):
    """Build the git setup of a developer who signs commits, runs hooks, and is mid-hook."""
    hooks = tmp_path / 'hostile-hooks'
    hooks.mkdir()
    hook = hooks / 'pre-commit'
    hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    hook.chmod(0o755)
    config = tmp_path / 'hostile.gitconfig'
    config.write_text(
        '[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /nonexistent/gpg\n'
        f'[core]\n\thooksPath = {hooks.as_posix()}\n[user]\n\tuseConfigOnly = true\n',
        encoding='utf-8',
    )
    return config


def _plain_commit(repo, env):
    """What a fixture did before: git commit, inheriting whatever ``env`` carries."""
    base = {key: value for key, value in env.items() if not key.startswith('GIT_')}
    return subprocess.run(
        ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'x'],
        cwd=repo,
        env={**base, 'GIT_CONFIG_GLOBAL': env['GIT_CONFIG_GLOBAL'], 'GIT_CONFIG_NOSYSTEM': '1'},
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.skipif(os.name == 'nt', reason='the hostile pre-commit hook is a POSIX shell script')
def test_fixture_commits_ignore_the_developers_signing_hooks_and_config(tmp_path, monkeypatch):
    config = _hostile_user_setup(tmp_path)
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(config))
    # The same developer through ~/.gitconfig, for a git that has no GIT_CONFIG_GLOBAL
    monkeypatch.setenv('HOME', str(tmp_path))
    (tmp_path / '.gitconfig').write_text(config.read_text(encoding='utf-8'), encoding='utf-8')
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'a.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')

    # The control: with that setup in effect a plain commit does not succeed
    pipediff_git_helpers.run_git(repo, 'init', '-q')
    pipediff_git_helpers.run_git(repo, 'add', 'a.pipe')
    assert _plain_commit(repo, dict(os.environ)).returncode != 0

    # The fixture does, and the committed file is readable at HEAD
    pipediff_git_helpers.commit_all(repo, 'init', 'a.pipe')
    assert resolve_git_ref('HEAD', str(repo / 'a.pipe')) == SAMPLE_PIPE


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_fixture_commits_never_land_in_an_inherited_repository(tmp_path, monkeypatch):
    # A test run from a git hook inherits GIT_DIR/GIT_INDEX_FILE/GIT_WORK_TREE of the
    # outer repository; the fixture's commits must go to its own repository, not there
    outer = tmp_path / 'outer'
    outer.mkdir()
    pipediff_git_helpers.run_git(outer, 'init', '-q')
    monkeypatch.setenv('GIT_DIR', str(outer / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(outer))
    monkeypatch.setenv('GIT_INDEX_FILE', str(outer / '.git' / 'index'))
    inner = tmp_path / 'inner'
    inner.mkdir()
    (inner / 'a.pipe').write_text(json.dumps(SAMPLE_PIPE), encoding='utf-8')

    init_repo(inner, 'a.pipe')

    assert (inner / '.git').is_dir()
    assert pipediff_git_helpers.run_git(inner, 'rev-parse', 'HEAD', check=False).returncode == 0
    assert pipediff_git_helpers.run_git(outer, 'rev-parse', '--verify', 'HEAD', check=False).returncode != 0


def test_fixture_git_commands_are_bounded_and_never_read_stdin(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(args, kwargs['timeout'])

    monkeypatch.setattr(pipediff_git_helpers.subprocess, 'run', fake_run)
    with pytest.raises(subprocess.TimeoutExpired):  # a wedged git fails the test instead of hanging the run
        pipediff_git_helpers.run_git(tmp_path, 'status')

    assert seen['timeout'] == pipediff_git_helpers.GIT_TIMEOUT_SECONDS
    assert seen['stdin'] is subprocess.DEVNULL
    assert seen['env']['GIT_CONFIG_NOSYSTEM'] == '1'
    assert seen['env']['GIT_CONFIG_GLOBAL'] == os.devnull
    assert not any(key in seen['env'] for key in ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE'))


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
