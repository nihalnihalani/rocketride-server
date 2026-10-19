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
import posixpath
import re
import subprocess

from ._pipejson import PipeDiffError, parse_pipe_json

# Upper bound so a wedged git process can never hang the CLI indefinitely.
_GIT_TIMEOUT_SECONDS = 30

# The git tree-entry modes of a committed symbolic link and of a directory.
_SYMLINK_MODE = '120000'
_TREE_MODE = '040000'

# Most links followed from one path at the ref before giving up (SYMLOOP_MAX).
_MAX_SYMLINK_HOPS = 40


def resolve_git_ref(ref: str, file_path: str) -> dict | None:
    """
    Load a pipeline file's contents at a specific git ref.

    Resolves ``file_path`` to its repository-relative location, verifies that
    ``ref`` names a commit, walks that path through the tree at ``ref`` (following
    each symlink, on the file or on a directory, as it was committed there, and
    recovering the tracked case of any component on a case-insensitive
    filesystem), and runs ``git show <ref>:<relative-path>`` to retrieve the file
    as it existed at ``ref``, then parses and validates the result. Used to diff a
    working-tree ``.pipe`` file against an arbitrary commit, branch, or tag.

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
            out, a symlink at the ref leaves the repository or loops, or the
            retrieved contents are not a valid pipeline.
    """
    # Find the repository through the file's physical directory, so the path
    # matches the top level ``git rev-parse --show-toplevel`` reports even when
    # the repo is reached through a symlinked directory. The directory goes to
    # realpath as given, not through abspath first: abspath folds ``lnk/..`` as
    # text, but the OS opens it as the parent of lnk's target. Each component is
    # spelled with its on-disk case, which is what git reports on a
    # case-insensitive filesystem.
    file_dir = _on_disk_case(os.path.realpath(os.path.dirname(file_path) or os.curdir))
    repo_root = _repository_root(file_dir, file_path)

    # The path below the repository root, as typed, so that a directory symlink
    # inside the repository stays a symlink and is looked up at the ref as the
    # link committed there. A ``..`` after a symlink is resolved on disk instead.
    parts = _typed_components(file_path, repo_root)
    if parts is None:
        abs_path = _on_disk_case(os.path.join(file_dir, os.path.basename(file_path)))
        parts = _repo_relative(abs_path, repo_root, file_path).split('/')

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

    # Walk the path through the tree as it was at the ref, one component at a
    # time, following every symlink as committed there (not as it is now), and
    # recovering the tracked spelling of any component that differs only in case.
    rel_path = _resolve_in_ref(repo_root, ref, parts)
    if rel_path is None:
        return None
    spec = f'{ref}:{rel_path}'

    result = _run_git(['-C', repo_root, 'show', spec], f'reading {spec}')
    if result.returncode != 0:
        raise PipeDiffError(f'git show {spec} failed: {result.stderr.strip()}')

    return parse_pipe_json(result.stdout, spec)


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


def _on_disk_case(path: str) -> str:
    """
    Spell an absolute path with the case each existing component has on disk.

    On a case-insensitive filesystem ``RepoDir/flows/rag.pipe`` opens the same
    file as ``RepoDir/Flows/rag.pipe``, but git's tree lookup and its reported
    top level use the stored case. Components are matched against their
    directory's listing (only to a name that is the same file), so on a
    case-sensitive filesystem nothing changes. Components that cannot be listed
    or do not exist are kept as given.
    """
    drive, rest = os.path.splitdrive(path)
    current = drive + os.sep
    for part in [part for part in rest.split(os.sep) if part]:
        candidate = os.path.join(current, part)
        try:
            entries = os.listdir(current)
        except OSError:
            entries = []
        if part not in entries:
            wanted = part.casefold()
            for entry in entries:
                if entry.casefold() == wanted and _same_file(os.path.join(current, entry), candidate):
                    candidate = os.path.join(current, entry)
                    break
        current = candidate
    return current


def _same_file(first: str, second: str) -> bool:
    """Report whether two paths name the same filesystem entry (links not followed)."""
    try:
        a, b = os.lstat(first), os.lstat(second)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _typed_components(file_path: str, repo_root: str) -> list[str] | None:
    """
    Return the components of ``file_path`` below ``repo_root``, exactly as typed.

    Directory symlinks inside the repository are left in place (not resolved),
    so each one can be looked up at the ref as the link committed there.

    Returns:
        The components below the repository root, or ``None`` when the typed path
        never passes through the root, or has a ``..`` below it that follows a
        symlink (or leaves the root). On POSIX ``..`` after a link is the parent
        of the link's *target*, which only the filesystem can say, so those paths
        are resolved on disk instead; after a real directory it is its parent.
    """
    typed = file_path if os.path.isabs(file_path) else os.path.join(os.getcwd(), file_path)
    drive, rest = os.path.splitdrive(typed)
    parts = [part for part in re.split(r'[\\/]' if os.name == 'nt' else '/', rest) if part not in ('', '.')]
    current = drive + os.sep
    for index in range(len(parts) + 1):
        if _same_directory(current, repo_root):
            return _collapse_dotdot(repo_root, parts[index:])
        if index == len(parts):
            break
        # Before the root, ``..`` means the physical parent (lexical on Windows)
        if parts[index] == '..':
            current = os.path.dirname(current if os.name == 'nt' else os.path.realpath(current))
        else:
            current = os.path.join(current, parts[index])
    return None


def _collapse_dotdot(repo_root: str, parts: list[str]) -> list[str] | None:
    """Apply each ``..`` in ``parts`` to the real directory before it, or return ``None`` after a link."""
    kept: list[str] = []
    for part in parts:
        if part != '..':
            kept.append(part)
        elif kept and not os.path.islink(os.path.join(repo_root, *kept)):
            kept.pop()
        else:
            return None
    return kept


def _same_directory(first: str, second: str) -> bool:
    """Report whether two paths name the same directory (links followed)."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _resolve_in_ref(repo_root: str, ref: str, parts: list[str]) -> str | None:
    """
    Resolve ``parts`` to a repository-relative path as the tree at ``ref`` has it.

    Walks the path one component at a time. A component that is a symlink at the
    ref is replaced by the link text stored there, which is read relative to the
    directory holding the link; ``..`` is applied to the path resolved so far, so
    it means the parent of a link's target, as on disk. Git trees never traverse
    links, so this is the only way to read a file reached through one.

    A component the caller typed that is not in the tree under the spelling given,
    but is under one that differs only in case, takes the tracked spelling when
    both name the same entry on disk (a case-insensitive filesystem). On a
    case-sensitive one they are two entries, so nothing matches. Link text is
    taken as committed.

    Returns:
        The repository-relative path of the entry at ``ref``, or ``None`` when
        the path does not exist there (including a link to such a path).

    Raises:
        PipeDiffError: If a link points outside the repository, links nest more
            than ``_MAX_SYMLINK_HOPS`` deep (a loop), or git cannot list the tree.
    """
    requested = '/'.join(parts)
    pending = [(part, True) for part in reversed(parts)]  # a stack: the next component is last
    resolved: list[str] = []
    listings: dict[str, dict[str, str]] = {}
    last_link = ''
    hops = 0

    while pending:
        part, typed = pending.pop()
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved:
                raise PipeDiffError(f'{last_link}, outside the repository')
            resolved.pop()
            continue

        directory = '/'.join(resolved)
        if directory not in listings:
            listings[directory] = _list_tree(repo_root, ref, directory)
        entries = listings[directory]
        name = part
        if name not in entries and typed:
            name = _tracked_spelling(repo_root, resolved, part, entries)
        mode = entries.get(name)
        if mode is None:
            return None

        if mode == _SYMLINK_MODE:
            hops += 1
            if hops > _MAX_SYMLINK_HOPS:
                raise PipeDiffError(f'{ref}:{requested}: too many levels of symbolic links')
            link_path = '/'.join([*resolved, name])
            link = _run_git(
                ['-C', repo_root, 'cat-file', 'blob', f'{ref}:{link_path}'], f'reading link {ref}:{link_path}'
            )
            if link.returncode != 0:
                raise PipeDiffError(f'git cat-file {ref}:{link_path} failed: {link.stderr.strip()}')
            target = link.stdout
            last_link = f'{ref}:{link_path} is a symlink to {target!r}'
            if posixpath.isabs(target):
                raise PipeDiffError(f'{last_link}, outside the repository')
            pending.extend((piece, False) for piece in reversed(target.split('/')))
            continue

        resolved.append(name)
        # Only a tree can be walked into; a file (or submodule) with more path
        # after it is no path at all
        if pending and mode != _TREE_MODE:
            return None

    return '/'.join(resolved) if resolved else None


def _list_tree(repo_root: str, ref: str, directory: str) -> dict[str, str]:
    """
    Return ``{entry name: git file mode}`` for ``directory`` ('' is the root) at ``ref``.

    The directory is named as ``<ref>:<directory>`` and not as a pathspec, so a
    name that looks like pathspec magic (``:(top)x``) is still taken literally.
    The walker only asks for directories it has already seen as tree entries.
    """
    listing = _run_git(['-C', repo_root, 'ls-tree', '-z', f'{ref}:{directory}'], f'listing {ref}:{directory or "."}')
    if listing.returncode != 0:
        raise PipeDiffError(f'git ls-tree {ref}:{directory or "."} failed: {listing.stderr.strip()}')
    entries: dict[str, str] = {}
    for entry in listing.stdout.split('\0'):
        meta, _tab, name = entry.partition('\t')
        if meta:
            entries[name] = meta.split(' ', 1)[0]
    return entries


def _tracked_spelling(repo_root: str, resolved: list[str], part: str, entries: dict[str, str]) -> str:
    """
    Find the tracked spelling of ``part`` when it differs only in case, else ``part``.

    A candidate counts only when it is the same directory entry on disk as
    ``part`` (links not followed), so on a case-sensitive filesystem, where two
    spellings are two entries, nothing matches.
    """
    wanted = part.casefold()
    typed_path = os.path.join(repo_root, *resolved, part)
    for name in entries:
        if name.casefold() == wanted and _same_file(os.path.join(repo_root, *resolved, name), typed_path):
            return name
    return part


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
