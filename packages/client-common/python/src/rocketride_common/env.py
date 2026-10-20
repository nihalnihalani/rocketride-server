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
Workspace ``.env`` handling shared by RocketRide client front-ends.

The reader loads the workspace ``.env`` into ``os.environ`` without
overriding the real environment (real environment wins). The writer is
line-preserving: credential updates rewrite only the keys they own and
leave every other line of the user's ``.env`` (comments, unrelated
variables, ordering, line endings) untouched.

A damaged or unreadable ``.env`` never crashes a command: the reader warns
once and carries on (see :func:`load_dot_env`), and the writer refuses to
rewrite a file it cannot read faithfully (see :func:`write_dot_env`).

Behavioral twin of ``client-common/typescript``'s ``env.ts`` for every valid
file - changes to valid-file behavior must be mirrored there. A leading UTF-8
byte-order mark is valid: both readers ignore it (``env.ts`` through
``String.trim()``), and this writer carries a BOM it finds through unchanged and
never adds one. For a damaged or unreadable file the two intentionally differ,
as of this change:

- Invalid UTF-8: Python skips each assignment line holding an invalid byte
  rather than apply a value it could not read, and applies every other line,
  with one warning to stderr. ``env.ts`` reads the bad bytes as U+FFFD and
  assigns the damaged lines too, silently.
- NUL characters: Python skips each assignment containing one, with a
  warning. ``env.ts`` assigns it to ``process.env``, which silently
  truncates the name or value at the NUL.
- A name or value this process's environment cannot hold (non-ASCII text when
  the filesystem encoding is ASCII, which is how the engine's embedded
  interpreter starts on Linux): Python skips the assignment with a warning.
  ``env.ts`` has no such limit.
- An unreadable ``.env``: Python warns and treats it as absent. ``env.ts``
  throws from ``readFileSync`` (EACCES) at CLI start-up. A directory named
  ``.env`` is skipped silently by Python and throws EISDIR in ``env.ts``.
- Rewriting: Python refuses, with :class:`DotEnvError`, to touch a file that is
  not valid UTF-8, contains NUL, assigns a ``ROCKETRIDE_*`` connection variable a
  value this process cannot store, or cannot be read. ``env.ts`` rewrites a
  non-UTF-8 file with U+FFFD in place of the bad bytes, and throws on an
  unreadable one. Python also keeps the file's own line endings; ``env.ts``
  rewrites every line ending as LF.
"""

import os
import re
import sys
from typing import Dict, Iterator, List, Optional, Tuple

# The two connection pairs the clients read and write
ENV_DEV_URI = 'ROCKETRIDE_URI'
ENV_DEV_APIKEY = 'ROCKETRIDE_APIKEY'
ENV_DEPLOY_URI = 'ROCKETRIDE_DEPLOY_URI'
ENV_DEPLOY_APIKEY = 'ROCKETRIDE_DEPLOY_APIKEY'

# The names the clients read from, and decide by, the connection pairs
_CONNECTION_KEYS = frozenset({ENV_DEV_URI, ENV_DEV_APIKEY, ENV_DEPLOY_URI, ENV_DEPLOY_APIKEY})

# The standard hard-stop message for a missing deploy pair
NO_DEPLOY_TARGET_MESSAGE = 'No deployment target configured. Set ROCKETRIDE_DEPLOY_URI / ROCKETRIDE_DEPLOY_APIKEY (or pass --uri/--apikey) - the development connection is never a deploy fallback.'


class DotEnvError(Exception):
    """The ``.env`` cannot be rewritten faithfully, so it was left untouched."""


def parse_env_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Parse one ``.env`` line into a key/value pair.

    Supports ``KEY=VALUE``, an optional ``export `` prefix, single or
    double quotes around the value, and ``#`` comment lines.

    Args:
        line: Raw line from the file.

    Returns:
        The parsed (key, value) pair, or None for non-assignment lines.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        return None
    if stripped.startswith('export '):
        stripped = stripped[7:].strip()
    eq = stripped.find('=')
    if eq <= 0:
        return None
    key = stripped[:eq].strip()
    value = stripped[eq + 1 :].strip()
    # Strip one matching pair of surrounding quotes
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return key, value


# A UTF-8 byte-order mark (what Windows PowerShell 5's Set-Content -Encoding UTF8
# writes) is not part of the first name; env.ts gets this from String.trim()
_BOM = b'\xef\xbb\xbf'
_BOM_TEXT = _BOM.decode('utf-8')

# The line ends of a text-mode open() with universal newlines: \n, \r\n and a lone \r.
# A UTF-8 continuation byte is never 0x0A or 0x0D, so splitting the bytes agrees with
# splitting the decoded text.
_BYTE_LINE_END = re.compile(rb'\r\n|\r|\n')
_TEXT_LINE_END = re.compile(r'\r\n|\r|\n')


def _line_of(raw: bytes, offset: int) -> int:
    """Return the 1-based line number of byte ``offset`` in ``raw``."""
    return len(_BYTE_LINE_END.findall(raw[:offset])) + 1


def _byte_lines(raw: bytes) -> Iterator[Tuple[int, int, bytes]]:
    """
    Yield ``(line number, byte offset of the line, the line without its end)`` for every
    line of ``raw`` after a leading byte-order mark.
    """
    offset = len(_BOM) if raw.startswith(_BOM) else 0
    number = 1
    for end in _BYTE_LINE_END.finditer(raw, offset):
        yield number, offset, raw[offset : end.start()]
        number, offset = number + 1, end.end()
    yield number, offset, raw[offset:]


def _count(number: int, noun: str) -> str:
    """Return ``number`` with ``noun`` in the right grammatical number ('1 line', '2 lines')."""
    return f'{number} {noun}' if number == 1 else f'{number} {noun}s'


def _split_lines(text: str) -> List[Tuple[str, str]]:
    """
    Split ``text`` into ``(line, its line end)`` pairs, the line end being '' for a last line without one.

    Splits where the reader does (LF, CRLF and a lone CR), unlike ``str.splitlines``, which
    also splits at form feeds, U+2028 and others and so would cut a value in two.
    """
    lines: List[Tuple[str, str]] = []
    position = 0
    for match in _TEXT_LINE_END.finditer(text):
        lines.append((text[position : match.start()], match.group()))
        position = match.end()
    if position < len(text):
        lines.append((text[position:], ''))
    return lines


def _storable(text: str) -> bool:
    """
    Report whether this process's environment can hold ``text``.

    ``os.environ`` encodes every name and value with the filesystem encoding, so
    where that is ASCII (the engine's embedded interpreter on Linux starts that
    way) any non-ASCII text raises ``UnicodeEncodeError`` on assignment.
    """
    try:
        os.fsencode(text)
    except UnicodeError:
        return False
    return True


def _read_assignments(env_path: str, problems: List[str]) -> List[Tuple[int, str, str]]:
    """
    Read every usable assignment in ``env_path``.

    Anything wrong with the file is described in ``problems`` instead of being
    raised. A description names the kind of problem and a position (a line
    number or byte offset), never any content of the file.

    A line is judged on its own: an assignment line that holds an invalid UTF-8
    byte or a NUL is left out, because what it would assign is not what the
    file's author wrote, and every other line is kept.

    Args:
        env_path: Path of the ``.env`` file.
        problems: Receives one short description per kind of problem found.

    Returns:
        The ``(line number, key, value)`` assignments to apply, in file order.
        Empty when the file is not a readable regular file.
    """
    if not os.path.isfile(env_path):
        # A directory is not a damaged file: `.env/` is a common virtualenv name
        # and has never been read, so it stays silent
        if not os.path.isdir(env_path):
            problems.append('is not a regular file, so it was ignored')
        return []
    try:
        with open(env_path, 'rb') as f:
            raw = f.read()
    except OSError as exc:
        problems.append(f'cannot be read ({exc.strerror or type(exc).__name__}), so it was ignored')
        return []

    assignments: List[Tuple[int, str, str]] = []
    first_invalid: Optional[Tuple[int, int]] = None  # (byte offset, line number)
    invalid_lines: List[int] = []
    nul_lines: List[int] = []
    for number, offset, line in _byte_lines(raw):
        try:
            text = line.decode('utf-8')
            damaged = False
        except UnicodeDecodeError as exc:
            # The replacement characters only let the line be recognised as an
            # assignment (or a comment); a damaged assignment is never applied
            text = line.decode('utf-8', errors='replace')
            damaged = True
            if first_invalid is None:
                first_invalid = (offset + exc.start, number)
        pair = parse_env_line(text)
        if not pair:
            continue
        # os.environ raises ValueError on a NUL in a name or value (a UTF-16 file
        # reads as valid UTF-8 full of them): skip the line rather than crash
        has_nul = '\0' in pair[0] or '\0' in pair[1]
        if damaged:
            invalid_lines.append(number)
        if has_nul:
            nul_lines.append(number)
        if not (damaged or has_nul):
            assignments.append((number, pair[0], pair[1]))

    if first_invalid is not None:
        offset, number = first_invalid
        effect = (
            f'{_count(len(invalid_lines), "assignment line")} holding invalid bytes '
            f'{"was" if len(invalid_lines) == 1 else "were"} skipped (first on line {invalid_lines[0]})'
            if invalid_lines
            else 'no assignment line is affected'
        )
        problems.append(f'is not valid UTF-8 (first invalid byte at offset {offset}, on line {number}); {effect}')
    if nul_lines:
        problems.append(
            f'has {_count(len(nul_lines), "assignment line")} containing NUL characters, which '
            f'{"was" if len(nul_lines) == 1 else "were"} skipped '
            f'(first on line {nul_lines[0]}; is the file UTF-16?)'
        )
    return assignments


def _warn(env_path: str, problems: List[str]) -> None:
    """
    Write one ``Warning:`` line to stderr naming ``env_path`` and its problems.

    Best effort: a closed or unwritable stderr must never turn a recoverable
    problem into a crash.
    """
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(f'Warning: {env_path} {"; ".join(problems)}.\n')
        stream.flush()
    except (OSError, ValueError, UnicodeError):
        pass


def load_dot_env(cwd: Optional[str] = None) -> None:
    """
    Load ``<cwd>/.env`` into ``os.environ`` without overriding variables
    the real environment already defines (real environment wins).

    A damaged or unreadable ``.env`` never crashes the command, and is never
    ignored silently: the loader writes ONE ``Warning:`` line to stderr naming
    the file and what is wrong (line numbers, counts and a byte offset, never
    any content of the file) and then carries on. Every line is judged on its
    own, so one bad line never costs the valid ones, and a line is either
    applied exactly as written or left out - a value is never altered:

    - Invalid UTF-8: each assignment line holding an invalid byte is skipped,
      because it cannot say what its author meant (a credential with a
      replacement character in it is a different credential, not a damaged
      one). Comments and every other line are unaffected.
    - NUL characters (a UTF-16 file reads as valid UTF-8 full of them): each
      assignment containing one is skipped, because ``os.environ`` rejects it.
    - A name or value this process's environment cannot hold: ``os.environ``
      encodes with the filesystem encoding, which is ASCII in the engine's
      embedded interpreter on Linux, so non-ASCII text cannot be assigned
      there. Such an assignment is skipped.
    - Unreadable (permissions), or not a regular file (a FIFO, say): treated
      as no ``.env`` at all, which is a valid state (defaults, flags and the
      real environment). A directory named ``.env`` (a virtualenv, commonly)
      is skipped without a warning, as it always has been.

    Precedence is unchanged: a variable the real environment defines is never
    overridden, and the first usable assignment of a variable in the file wins
    (so a skipped line does not shadow a later assignment of the same name).
    The file is only read, never modified.

    Args:
        cwd: Directory holding the ``.env`` file (default: os.getcwd()).
    """
    env_path = os.path.join(cwd or os.getcwd(), '.env')
    if not os.path.exists(env_path):
        return
    # step: read the whole file, collect what is wrong with it, then apply every
    # usable assignment (setdefault, so the real environment wins)
    problems: List[str] = []
    unstorable: List[int] = []
    for number, key, value in _read_assignments(env_path, problems):
        try:
            os.environ.setdefault(key, value)
        except (UnicodeError, ValueError):
            # Nothing was assigned: os.environ encodes before it calls putenv
            unstorable.append(number)
    if unstorable:
        problems.append(
            f'has {_count(len(unstorable), "assignment line")} whose name or value this process cannot store '
            f'(filesystem encoding {sys.getfilesystemencoding()}), which '
            f'{"was" if len(unstorable) == 1 else "were"} skipped (first on line {unstorable[0]})'
        )
    if problems:
        _warn(env_path, problems)


def _unfaithful_reason(raw: bytes) -> Optional[str]:
    """
    Say why rewriting ``raw`` as UTF-8 text would not preserve it, or ``None``.

    The reason names the problem and a position, never any content. A connection
    variable this process cannot store is a reason too: the reader skipped it, so
    the caller never saw it (a deploy pair "already pointing elsewhere" included).
    Any other line it cannot store is left alone by the writer, like every line it
    does not own.
    """
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        return f'it is not valid UTF-8 (first invalid byte at offset {exc.start}, on line {_line_of(raw, exc.start)})'
    nul = raw.find(b'\0')
    if nul >= 0:
        return f'it contains a NUL character (first on line {_line_of(raw, nul)}; is the file UTF-16?)'
    for number, _offset, line in _byte_lines(raw):
        pair = parse_env_line(line.decode('utf-8'))
        if pair and pair[0] in _CONNECTION_KEYS and not _storable(pair[1]):
            return (
                'it assigns a connection variable a value this process cannot store in its environment '
                f'(filesystem encoding {sys.getfilesystemencoding()}, on line {number})'
            )
    return None


def _read_for_update(env_path: str) -> Optional[str]:
    """
    Read the existing ``.env`` for rewriting, or ``None`` when there is none.

    Raises:
        DotEnvError: If the file exists but cannot be rewritten faithfully
            (not a regular file, unreadable, not UTF-8, holding NUL, or assigning
            a connection variable a value this process cannot store).
    """
    if not os.path.exists(env_path):
        return None
    reason: Optional[str] = None
    raw = b''
    if not os.path.isfile(env_path):
        reason = 'it is not a regular file'
    else:
        try:
            with open(env_path, 'rb') as f:
                raw = f.read()
        except OSError as exc:
            reason = f'it cannot be read ({exc.strerror or type(exc).__name__})'
        else:
            reason = _unfaithful_reason(raw)
    if reason is not None:
        raise DotEnvError(f'Refusing to update {env_path}: {reason}. Fix or remove it, then run the command again.')
    return raw.decode('utf-8')


def check_dot_env_writable(cwd: Optional[str] = None) -> None:
    """
    Fail now, before any prompt or network call, if :func:`write_dot_env` would refuse.

    Args:
        cwd: Directory holding the ``.env`` file (default: os.getcwd()).

    Raises:
        DotEnvError: If the existing ``.env`` cannot be rewritten faithfully.
    """
    _read_for_update(os.path.join(cwd or os.getcwd(), '.env'))


def write_dot_env(updates: Dict[str, str], cwd: Optional[str] = None) -> str:
    """
    Update keys in ``<cwd>/.env``, preserving every other line verbatim.

    Existing assignments to the given keys are rewritten in place; keys
    with no existing assignment are appended at the end. Creates the file
    when absent. Every line that is not rewritten keeps its own line end
    (LF, CRLF or CR), whatever the platform; a new line gets the file's first
    line end, and a new file uses LF.

    Unlike the reader, the writer does not carry on past damage: a file that
    is not valid UTF-8, contains NUL, assigns a connection variable a value this
    process cannot store, is not a regular file, or cannot be read cannot be
    rewritten without altering lines this function does not own, or without
    acting on a value the reader could not see (a deploy pair "already
    pointing elsewhere" must never be overwritten). It is refused, untouched.

    Args:
        updates: Key/value pairs to persist.
        cwd: Directory holding the ``.env`` file (default: os.getcwd()).

    Returns:
        The path of the file written.

    Raises:
        DotEnvError: If the existing file cannot be rewritten faithfully. The
            message names the file and the problem, never its contents.
    """
    env_path = os.path.join(cwd or os.getcwd(), '.env')
    pending = dict(updates)
    existing = _read_for_update(env_path)
    # A byte-order mark is neither parsed into the first name nor dropped nor added:
    # it is carried over exactly as found
    bom = _BOM_TEXT if existing is not None and existing.startswith(_BOM_TEXT) else ''
    lines = _split_lines(existing.removeprefix(bom)) if existing is not None else []
    # Appended lines end the way the file's lines do (LF for a file with none)
    newline = next((ending for _text, ending in lines if ending), '\n')

    # step: rewrite lines that assign one of the updated keys
    output: List[Tuple[str, str]] = []
    for text, ending in lines:
        pair = parse_env_line(text)
        if pair and pair[0] in pending:
            output.append((f'{pair[0]}={pending.pop(pair[0])}', ending))
        else:
            output.append((text, ending))

    # step: append keys that had no existing assignment
    if pending:
        while output and not output[-1][0].strip():
            output.pop()
        for key, value in pending.items():
            output.append((f'{key}={value}', newline))

    # step: write the bytes as built. newline='' stops the platform from turning each
    # LF into CRLF (Windows) or the reverse; the only ending added is the final one a
    # file ending without a line end gets
    with open(env_path, 'w', encoding='utf-8', newline='') as f:
        f.write(bom + ''.join(text + (ending or newline) for text, ending in output))
    return env_path
