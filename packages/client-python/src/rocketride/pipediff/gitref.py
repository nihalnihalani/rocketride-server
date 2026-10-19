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
Git ref resolution for ``rocketride diff --git <ref> <file.pipe>``.

This module reads a pipeline file's contents at a given git ref so the working
tree can be diffed against history (for example ``rocketride diff --git HEAD
pipeline.pipe``). It shells out to ``git show`` via :mod:`subprocess` with an
argument list — never a shell string — so pipeline paths and refs cannot inject
shell commands.

Like the rest of :mod:`rocketride.pipediff`, this never contacts the RocketRide
engine or the network; ``git`` is the only external process invoked.

Functions:
    resolve_git_ref: Return the parsed pipeline at ``ref``, or ``None`` if the
        file does not exist in that ref (treated by the caller as an all-added
        pipeline).
"""

from __future__ import annotations

import os
import subprocess

from .engine import PipeDiffError, _parse_pipe_json

# Upper bound so a wedged git process can never hang the CLI indefinitely.
_GIT_TIMEOUT_SECONDS = 30

# The git tree-entry mode of a committed symbolic link.
_SYMLINK_MODE = '120000'


def resolve_git_ref(ref: str, file_path: str) -> dict | None:
    """
    Load a pipeline file's contents at a specific git ref.

    Resolves ``file_path`` to its repository-relative location, verifies that
    ``ref`` names a commit, and runs ``git show <ref>:<relative-path>`` to
    retrieve the file as it existed at ``ref``, then parses and validates the
    result. Used to diff a working-tree
    ``.pipe`` file against an arbitrary commit, branch, or tag.

    Args:
        ref: A git revision (commit sha, branch, tag, ``HEAD``, ``HEAD~1``, ...).
        file_path: Path to the working-tree ``.pipe`` file (absolute or relative
            to the current working directory).

    Returns:
        The parsed and validated pipeline ``dict`` at ``ref``, or ``None`` if the
        file does not exist in ``ref`` (the caller treats this as "everything is
        new").

    Raises:
        PipeDiffError: If the path is not inside a git repository, the ref is
            unknown (or does not name a commit), ``git`` is unavailable or times
            out, or the retrieved contents are not a valid pipeline.
    """
    # Resolve symlinks in the directory only (realpath of the parent), so the path
    # matches the physical top level ``git rev-parse --show-toplevel`` reports
    # even when the repo is reached through a symlinked directory, while the file
    # itself is looked up under the name given -- ``git show <ref>:<FILE>``, as
    # documented. Resolving the file too made an untracked link to a tracked
    # file compare against its target instead of being reported as new.
    given_path = os.path.abspath(file_path)
    file_dir = os.path.realpath(os.path.dirname(given_path))
    abs_path = os.path.join(file_dir, os.path.basename(given_path))

    repo_root = _repository_root(file_dir, file_path)
    rel_path = _repo_relative(abs_path, repo_root, file_path)
    spec = f'{ref}:{rel_path}'

    # "Ref unknown" and "path absent from a known ref" must not be confused: the
    # first is a user error (exit 2), the second means "everything is new". Both
    # are decided on a git exit code, never on the wording of git's diagnostic —
    # a ref whose *name* contains a phrase like "does not exist in" is echoed
    # back in that diagnostic, and matching on it would silently downgrade a bad
    # ref into an all-added diff.
    verified = _run_git(
        ['-C', repo_root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}'],
        f'verifying ref {ref}',
    )
    if verified.returncode != 0:
        detail = verified.stderr.strip()
        suffix = f': {detail}' if detail else ''
        raise PipeDiffError(f'Unknown git ref {ref!r}{suffix}')

    # ``cat-file -e`` is the machine-readable existence check: exit 0 when the
    # object named by <ref>:<path> exists in that (already verified) ref, non-zero
    # when it does not.
    present = _run_git(['-C', repo_root, 'cat-file', '-e', spec], f'checking for {spec}')
    if present.returncode != 0:
        # On a case-insensitive filesystem a mis-cased FILE opens the tracked
        # file while git's tree lookup misses it; compare against that file
        # rather than reporting every node as added.
        rel_path = _same_file_in_ref(repo_root, ref, rel_path, abs_path) if os.path.exists(abs_path) else None
        if rel_path is None:
            return None
        spec = f'{ref}:{rel_path}'
    elif os.path.islink(abs_path) and _tree_mode(repo_root, ref, rel_path) == _SYMLINK_MODE:
        # A link committed as a link: ``git show`` would return its target path,
        # not a pipe. Compare the file the working-tree link reads instead.
        rel_path = _repo_relative(os.path.realpath(abs_path), repo_root, file_path)
        spec = f'{ref}:{rel_path}'
        present = _run_git(['-C', repo_root, 'cat-file', '-e', spec], f'checking for {spec}')
        if present.returncode != 0:
            return None

    result = _run_git(['-C', repo_root, 'show', spec], f'reading {spec}')
    if result.returncode != 0:
        raise PipeDiffError(f'git show {spec} failed: {result.stderr.strip()}')

    return _parse_pipe_json(result.stdout, spec)


def _repo_relative(path: str, repo_root: str, file_path: str) -> str:
    """
    Express ``path`` relative to ``repo_root`` in git's ``/``-separated form.

    Raises:
        PipeDiffError: If ``path`` lies outside the repository (a symlink whose
            target is elsewhere, for instance), which no ``<ref>:<path>`` names.
    """
    rel_path = os.path.relpath(path, repo_root)
    if rel_path == os.pardir or rel_path.startswith(os.pardir + os.sep):
        raise PipeDiffError(f'{file_path} resolves outside the repository at {repo_root}')
    return rel_path.replace(os.sep, '/')


def _tree_mode(repo_root: str, ref: str, rel_path: str) -> str | None:
    """Return the git file mode of ``rel_path`` in ``ref`` (``120000`` for a link), or ``None``."""
    listing = _run_git(['-C', repo_root, 'ls-tree', '-z', ref, '--', rel_path], f'listing {ref}:{rel_path}')
    if listing.returncode != 0:
        return None
    for entry in listing.stdout.split('\0'):
        meta, _tab, name = entry.partition('\t')
        if name == rel_path:
            return meta.split(' ', 1)[0]
    return None


def _same_file_in_ref(repo_root: str, ref: str, rel_path: str, abs_path: str) -> str | None:
    """
    Find the tracked spelling of ``rel_path`` when it differs only in case.

    Lists the entries of the file's directory in ``ref`` and returns the one
    whose name matches case-insensitively *and* is the same file on disk as
    ``abs_path``. On a case-sensitive filesystem two such names are two files,
    so nothing matches and the file is treated as new.
    """
    directory, _slash, name = rel_path.rpartition('/')
    listing = _run_git(
        ['-C', repo_root, 'ls-tree', '-z', '--name-only', ref, '--', f'{directory}/' if directory else '.'],
        f'listing {ref}:{directory or "."}',
    )
    if listing.returncode != 0:
        return None
    wanted = name.casefold()
    for candidate in listing.stdout.split('\0'):
        if candidate == rel_path or candidate.rpartition('/')[2].casefold() != wanted:
            continue
        candidate_path = os.path.join(repo_root, *candidate.split('/'))
        try:
            if os.path.samefile(candidate_path, abs_path):
                return candidate
        except OSError:
            continue
    return None


def _repository_root(file_dir: str, file_path: str) -> str:
    """
    Resolve the git repository root that contains ``file_dir``.

    Args:
        file_dir: A directory inside the repository (the file's parent).
        file_path: The original path, used only for error context.

    Returns:
        The absolute path to the repository top level.

    Raises:
        PipeDiffError: If ``file_dir`` is not inside a git repository (or git
            otherwise fails to resolve the top level).
    """
    result = _run_git(
        ['-C', file_dir, 'rev-parse', '--show-toplevel'],
        f'resolving repository for {file_path}',
    )
    if result.returncode != 0:
        raise PipeDiffError(f'Not a git repository (or unable to resolve it) for {file_path}: {result.stderr.strip()}')
    return result.stdout.strip()


def _run_git(args: list[str], context: str) -> subprocess.CompletedProcess:
    """
    Run a ``git`` subcommand with a fixed argument list and no shell.

    Args:
        args: Arguments passed to ``git`` (already split; never a shell string).
        context: A short description of the operation for error messages.

    Returns:
        The completed process (callers inspect ``returncode``/``stdout``/
        ``stderr``).

    Raises:
        PipeDiffError: If ``git`` is not found on ``PATH``, the call times out, or
            git's output is not decodable as UTF-8 (a blob that is not a text
            pipe file, for instance).
    """
    try:
        return subprocess.run(
            ['git', *args],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise PipeDiffError('git executable not found; --git requires git on PATH') from exc
    except subprocess.TimeoutExpired as exc:
        raise PipeDiffError(f'git timed out while {context}') from exc
    except UnicodeDecodeError as exc:
        raise PipeDiffError(f'git output is not valid UTF-8 while {context}: {exc}') from exc
