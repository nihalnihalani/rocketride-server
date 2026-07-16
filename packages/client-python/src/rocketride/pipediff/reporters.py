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
Rendering utilities for semantic ``.pipe`` pipeline diffs.

This module turns a :class:`~rocketride.pipediff.model.PipeDiff` (produced by the
pipediff engine) into three presentation formats used by the ``rocketride diff``
command:

    - ``render_human``    : colored, section-grouped text for interactive terminals
    - ``render_json``     : a single JSON-serializable document for tooling
    - ``render_markdown`` : compact, PR-comment-friendly Markdown for the GitHub Action

The renderers share a single normalization pass (``_organize``) so that every
format reports the same set of changes in the same deterministic order,
regardless of the order in which the engine emitted them. This determinism keeps
JSON output stable for snapshot tests and keeps PR comments from churning.

Design notes:
    - The renderers are intentionally *read-only* over the diff model: they never
      construct model objects, so they depend on the model dataclasses for typing
      only (guarded by ``TYPE_CHECKING``). This keeps the pipediff library free of
      import-time coupling between the reporters and the engine, and lets the
      module load even while sibling modules are still being written.
    - ANSI color constants are defined locally rather than imported from
      ``rocketride.cli.ui.colors``. The pipediff package is a library that the CLI
      depends on; importing back into the CLI would invert that layering. The
      constants below mirror the values in ``rocketride/cli/ui/colors.py``.
    - Callers decide whether color is appropriate (TTY detection, ``NO_COLOR``)
      and pass the result via ``use_color``; the renderer itself never inspects
      the environment.

Components:
    render_human: Human-readable, optionally colored diff report
    render_json: JSON-serializable diff document with a summary block
    render_markdown: Compact Markdown diff suitable for embedding in PR comments
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from .model import PipeDiff


# ANSI color codes. These mirror rocketride/cli/ui/colors.py; they are duplicated
# here so the pipediff library does not import from the CLI package (which would
# invert the dependency direction, since the CLI depends on pipediff).
_ANSI_RESET = '\033[0m'
_ANSI_RED = '\033[91m'
_ANSI_GREEN = '\033[92m'
_ANSI_YELLOW = '\033[93m'
_ANSI_GRAY = '\033[90m'

# Change markers shared across all output formats.
_MARK_ADDED = '+'
_MARK_REMOVED = '-'
_MARK_CHANGED = '~'

# Markdown marker glyphs (kept ASCII-safe and unambiguous in PR comments).
_MD_ADDED = '+'
_MD_REMOVED = '-'
_MD_CHANGED = '~'


class _Palette:
    """
    Small helper that applies (or suppresses) ANSI color per change kind.

    When ``use_color`` is false every method returns its argument unchanged, so
    the same rendering code path produces plain text for non-TTY output and for
    ``NO_COLOR`` environments without branching at each call site.
    """

    def __init__(self, use_color: bool):
        """Store whether color escapes should be emitted."""
        self._on = bool(use_color)

    def _wrap(self, code: str, text: str) -> str:
        """Wrap ``text`` in an ANSI ``code``/reset pair when color is enabled."""
        if not self._on:
            return text
        return f'{code}{text}{_ANSI_RESET}'

    def added(self, text: str) -> str:
        """Color ``text`` as an addition (green)."""
        return self._wrap(_ANSI_GREEN, text)

    def removed(self, text: str) -> str:
        """Color ``text`` as a removal (red)."""
        return self._wrap(_ANSI_RED, text)

    def changed(self, text: str) -> str:
        """Color ``text`` as a modification (yellow)."""
        return self._wrap(_ANSI_YELLOW, text)

    def dim(self, text: str) -> str:
        """Color ``text`` as secondary/dim (gray)."""
        return self._wrap(_ANSI_GRAY, text)


# =========================================================================
# NORMALIZATION
# =========================================================================


def _provider_added(node_change: Any) -> Optional[str]:
    """Return the provider to display for an added node."""
    return node_change.provider_new if node_change.provider_new is not None else node_change.provider_old


def _provider_removed(node_change: Any) -> Optional[str]:
    """Return the provider to display for a removed node."""
    return node_change.provider_old if node_change.provider_old is not None else node_change.provider_new


def _organize(diff: 'PipeDiff') -> Dict[str, Any]:
    """
    Collapse a :class:`PipeDiff` into a sorted, de-duplicated intermediate form.

    All three renderers consume this structure so that they agree on both the set
    of reported changes and their ordering. Node changes are aggregated by id: a
    node that has both a provider change and configuration changes (whether the
    engine emitted them as one ``NodeChange`` or several) is merged into a single
    ``changed`` entry.

    Args:
        diff: The pipeline diff to normalize.

    Returns:
        A dictionary with the following keys:
            - ``nodes_added``:   list of ``(id, provider)`` tuples, sorted by id
            - ``nodes_removed``: list of ``(id, provider)`` tuples, sorted by id
            - ``nodes_changed``: list of per-id dicts (provider change + config
              field changes), sorted by id
            - ``edges_added``:   list of ``(from_id, lane, to_id)`` tuples, sorted
            - ``edges_removed``: list of ``(from_id, lane, to_id)`` tuples, sorted
            - ``version_change``: the ``(old, new)`` tuple or ``None``
            - ``layout_changed``: bool
            - ``has_semantic_changes``: bool (delegates to the diff's property)
    """
    nodes_added: List[Tuple[str, Optional[str]]] = []
    nodes_removed: List[Tuple[str, Optional[str]]] = []
    changed: Dict[str, Dict[str, Any]] = {}

    for node_change in diff.node_changes:
        kind = node_change.kind
        if kind == 'added':
            nodes_added.append((node_change.id, _provider_added(node_change)))
        elif kind == 'removed':
            nodes_removed.append((node_change.id, _provider_removed(node_change)))
        else:
            # 'provider', 'config', or any future in-place change kind: fold into
            # a single per-id entry keyed by node id.
            entry = changed.setdefault(
                node_change.id,
                {
                    'id': node_change.id,
                    'provider_old': None,
                    'provider_new': None,
                    'has_provider_change': False,
                    'config_changes': [],
                },
            )
            if (
                node_change.provider_old is not None or node_change.provider_new is not None
            ) and node_change.provider_old != node_change.provider_new:
                entry['provider_old'] = node_change.provider_old
                entry['provider_new'] = node_change.provider_new
                entry['has_provider_change'] = True
            for field_change in node_change.field_changes or []:
                entry['config_changes'].append(field_change)

    # Sort config changes within each node for deterministic output.
    nodes_changed: List[Dict[str, Any]] = []
    for entry in changed.values():
        entry['config_changes'] = sorted(
            entry['config_changes'],
            key=lambda fc: (fc.path, fc.kind),
        )
        nodes_changed.append(entry)

    edges_added: List[Tuple[str, str, str]] = []
    edges_removed: List[Tuple[str, str, str]] = []
    for edge_change in diff.edge_changes:
        triple = (edge_change.from_id, edge_change.lane, edge_change.to_id)
        if edge_change.kind == 'added':
            edges_added.append(triple)
        elif edge_change.kind == 'removed':
            edges_removed.append(triple)

    return {
        'nodes_added': sorted(nodes_added, key=lambda t: t[0]),
        'nodes_removed': sorted(nodes_removed, key=lambda t: t[0]),
        'nodes_changed': sorted(nodes_changed, key=lambda e: e['id']),
        'edges_added': sorted(edges_added),
        'edges_removed': sorted(edges_removed),
        'version_change': diff.version_change,
        'layout_changed': bool(diff.layout_changed),
        'has_semantic_changes': bool(diff.has_semantic_changes),
    }


def _any_output(org: Dict[str, Any]) -> bool:
    """Return True when there is anything at all worth printing."""
    return bool(
        org['nodes_added']
        or org['nodes_removed']
        or org['nodes_changed']
        or org['edges_added']
        or org['edges_removed']
        or org['version_change']
        or org['layout_changed']
    )


def _fmt_value(value: Any) -> str:
    """
    Render a config value as a compact, readable string.

    Strings are returned bare; every other JSON type (numbers, booleans, ``None``,
    dicts, lists) is serialized with ``json.dumps`` so the type stays unambiguous
    (``null``/``true``/``false``) and nested structures render deterministically.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _summary_counts(org: Dict[str, Any]) -> Dict[str, int]:
    """Compute the integer counts used by summary lines and the JSON summary."""
    config_changes = sum(len(entry['config_changes']) for entry in org['nodes_changed'])
    provider_changes = sum(1 for entry in org['nodes_changed'] if entry['has_provider_change'])
    return {
        'nodes_added': len(org['nodes_added']),
        'nodes_removed': len(org['nodes_removed']),
        'nodes_changed': len(org['nodes_changed']),
        'provider_changes': provider_changes,
        'config_changes': config_changes,
        'edges_added': len(org['edges_added']),
        'edges_removed': len(org['edges_removed']),
    }


def _summary_phrase(org: Dict[str, Any]) -> str:
    """
    Build a one-line human summary such as ``2 nodes added, 1 edge removed``.

    Only non-zero categories are included. Version and layout changes are appended
    when present. When nothing changed the phrase is ``no semantic changes``.
    """
    counts = _summary_counts(org)
    parts: List[str] = []

    def _plural(n: int, singular: str) -> str:
        return f'{n} {singular}' if n == 1 else f'{n} {singular}s'

    if counts['nodes_added']:
        parts.append(f'{_plural(counts["nodes_added"], "node")} added')
    if counts['nodes_removed']:
        parts.append(f'{_plural(counts["nodes_removed"], "node")} removed')
    if counts['nodes_changed']:
        parts.append(f'{_plural(counts["nodes_changed"], "node")} changed')
    if counts['edges_added']:
        parts.append(f'{_plural(counts["edges_added"], "edge")} added')
    if counts['edges_removed']:
        parts.append(f'{_plural(counts["edges_removed"], "edge")} removed')

    version_change = org['version_change']
    if version_change:
        parts.append(f'version {_fmt_value(version_change[0])} → {_fmt_value(version_change[1])}')

    if org['layout_changed']:
        parts.append('layout changed')

    if not parts:
        return 'no semantic changes'
    return ', '.join(parts)


# =========================================================================
# HUMAN (TEXT) RENDERER
# =========================================================================


def _human_field_line(field_change: Any, palette: _Palette) -> str:
    """Render a single config FieldChange as an indented, marked text line."""
    path = field_change.path
    kind = field_change.kind
    if kind == 'added':
        body = f'{_MARK_ADDED} {path} = {_fmt_value(field_change.new)}'
        return '    ' + palette.added(body)
    if kind == 'removed':
        body = f'{_MARK_REMOVED} {path} = {_fmt_value(field_change.old)}'
        return '    ' + palette.removed(body)
    # changed
    old = _fmt_value(field_change.old)
    new = _fmt_value(field_change.new)
    return '    ' + palette.changed(f'{_MARK_CHANGED} {path}: ') + f'{old} ' + palette.dim('->') + f' {new}'


def render_human(diff: 'PipeDiff', *, use_color: bool) -> str:
    """
    Render a semantic pipe diff as grouped, optionally colored text.

    The report is organized into up to three sections — ``Nodes`` (additions,
    removals, provider changes), ``Edges`` (added/removed wiring), and ``Config``
    (per-node field changes) — followed by standalone ``Version`` and ``Layout``
    lines when applicable. Change markers are ``+`` (added, green), ``-`` (removed,
    red), and ``~`` (changed, yellow). Empty sections are omitted.

    Args:
        diff: The pipeline diff to render.
        use_color: When True, wrap markers and values in ANSI color escapes. The
            caller is responsible for deciding whether color is appropriate (TTY
            detection and ``NO_COLOR`` honoring live in the CLI); this function
            only applies the choice.

    Returns:
        A newline-joined string with no trailing newline. When there are no
        changes at all the string is ``No semantic changes.``.
    """
    org = _organize(diff)
    palette = _Palette(use_color)

    if not _any_output(org):
        return 'No semantic changes.'

    lines: List[str] = []
    lines.append(f'Pipeline diff: {_summary_phrase(org)}')

    # --- Nodes ---
    if org['nodes_added'] or org['nodes_removed'] or any(e['has_provider_change'] for e in org['nodes_changed']):
        lines.append('')
        lines.append('Nodes')
        for node_id, provider in org['nodes_added']:
            lines.append('  ' + palette.added(f'{_MARK_ADDED} {node_id} ({provider})'))
        for node_id, provider in org['nodes_removed']:
            lines.append('  ' + palette.removed(f'{_MARK_REMOVED} {node_id} ({provider})'))
        for entry in org['nodes_changed']:
            if entry['has_provider_change']:
                marker = palette.changed(f'{_MARK_CHANGED} {entry["id"]} provider: ')
                lines.append(
                    '  ' + marker + f'{entry["provider_old"]} ' + palette.dim('->') + f' {entry["provider_new"]}'
                )

    # --- Edges ---
    if org['edges_added'] or org['edges_removed']:
        lines.append('')
        lines.append('Edges')
        for from_id, lane, to_id in org['edges_added']:
            lines.append('  ' + palette.added(f'{_MARK_ADDED} {from_id} --{lane}--> {to_id}'))
        for from_id, lane, to_id in org['edges_removed']:
            lines.append('  ' + palette.removed(f'{_MARK_REMOVED} {from_id} --{lane}--> {to_id}'))

    # --- Config ---
    config_nodes = [e for e in org['nodes_changed'] if e['config_changes']]
    if config_nodes:
        lines.append('')
        lines.append('Config')
        for entry in config_nodes:
            lines.append(f'  {entry["id"]}')
            for field_change in entry['config_changes']:
                lines.append(_human_field_line(field_change, palette))

    # --- Version / Layout ---
    if org['version_change']:
        old = _fmt_value(org['version_change'][0])
        new = _fmt_value(org['version_change'][1])
        lines.append('')
        lines.append('Version: ' + f'{old} ' + palette.dim('->') + f' {new}')

    if org['layout_changed']:
        if not org['version_change']:
            lines.append('')
        lines.append(palette.dim('Layout: changed (ui/viewport)'))

    return '\n'.join(lines)


# =========================================================================
# JSON RENDERER
# =========================================================================


def _json_field_change(field_change: Any) -> Dict[str, Any]:
    """Serialize a single FieldChange into a plain dict."""
    return {
        'path': field_change.path,
        'kind': field_change.kind,
        'old': field_change.old,
        'new': field_change.new,
    }


def render_json(diff: 'PipeDiff') -> Dict[str, Any]:
    """
    Render a semantic pipe diff as a single JSON-serializable document.

    The returned structure is stable and deterministically ordered:

        {
            "nodes": {"added": [...], "removed": [...], "changed": [...]},
            "edges": {"added": [...], "removed": [...]},
            "summary": {...}
        }

    Each added/removed node is ``{"id", "provider"}``. Each changed node is
    ``{"id", "provider_change": {"old", "new"} | null, "config_changes": [...]}``
    where every config change is ``{"path", "kind", "old", "new"}``. Edges are
    ``{"from", "lane", "to"}``. The ``summary`` block carries counts, the version
    change (as ``[old, new]`` or ``null``), the layout flag, and the overall
    ``has_semantic_changes`` boolean.

    Args:
        diff: The pipeline diff to render.

    Returns:
        A dict containing only JSON-serializable values.
    """
    org = _organize(diff)

    nodes_added = [{'id': node_id, 'provider': provider} for node_id, provider in org['nodes_added']]
    nodes_removed = [{'id': node_id, 'provider': provider} for node_id, provider in org['nodes_removed']]

    nodes_changed: List[Dict[str, Any]] = []
    for entry in org['nodes_changed']:
        provider_change = None
        if entry['has_provider_change']:
            provider_change = {'old': entry['provider_old'], 'new': entry['provider_new']}
        nodes_changed.append(
            {
                'id': entry['id'],
                'provider_change': provider_change,
                'config_changes': [_json_field_change(fc) for fc in entry['config_changes']],
            }
        )

    edges_added = [{'from': from_id, 'lane': lane, 'to': to_id} for from_id, lane, to_id in org['edges_added']]
    edges_removed = [{'from': from_id, 'lane': lane, 'to': to_id} for from_id, lane, to_id in org['edges_removed']]

    counts = _summary_counts(org)
    version_change = list(org['version_change']) if org['version_change'] else None

    summary = {
        **counts,
        'version_change': version_change,
        'layout_changed': org['layout_changed'],
        'has_semantic_changes': org['has_semantic_changes'],
    }

    return {
        'nodes': {'added': nodes_added, 'removed': nodes_removed, 'changed': nodes_changed},
        'edges': {'added': edges_added, 'removed': edges_removed},
        'summary': summary,
    }


# =========================================================================
# MARKDOWN RENDERER
# =========================================================================


def _md_code(text: str) -> str:
    """
    Wrap ``text`` in a Markdown code span, safely handling embedded backticks.

    Per CommonMark, a code span may use a run of N backticks as its delimiter as
    long as the content contains no run of exactly N backticks; padding spaces are
    stripped by the renderer. This picks a delimiter longer than the longest
    internal backtick run so arbitrary values render literally.

    Line breaks are collapsed to spaces first. A CommonMark code span cannot span a
    blank line, so a newline in an untrusted value (node id, provider, lane, config
    value) would otherwise terminate the span and the enclosing bullet/table cell,
    letting the trailing text render as real Markdown (headings, ``@`` mentions,
    links) in the auto-posted PR comment. Neutralizing them here — the single choke
    point every value passes through — covers bullets, table cells, and the version
    line at once.
    """
    text = str(text).replace('\r', ' ').replace('\n', ' ')
    if '`' not in text:
        return f'`{text}`'
    longest = max(len(run) for run in re.findall(r'`+', text))
    fence = '`' * (longest + 1)
    return f'{fence} {text} {fence}'


def _md_cell(text: str) -> str:
    """
    Escape a string for use inside a Markdown table cell.

    GitHub's table parser splits on ``|`` even inside code spans, and literal
    newlines break the row, so both are neutralized here after any code-span
    formatting has been applied.
    """
    return str(text).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')


def _md_field_change(field_change: Any) -> str:
    """Render a config FieldChange as a compact Markdown 'change' fragment."""
    if field_change.kind == 'added':
        return f'{_MD_ADDED} {_md_code(field_change.new)}'
    if field_change.kind == 'removed':
        return f'{_MD_REMOVED} {_md_code(field_change.old)}'
    return f'{_md_code(field_change.old)} → {_md_code(field_change.new)}'


def render_markdown(diff: 'PipeDiff', *, title: Optional[str] = None) -> str:
    """
    Render a semantic pipe diff as compact, PR-comment-friendly Markdown.

    The output leads with a bold one-line summary, then grouped sections: ``Nodes``
    and ``Edges`` as bullet lists and ``Config`` as a table (``Node | Field |
    Change``). All node ids, providers, lanes, and values are wrapped in code
    spans; table cells additionally escape ``|`` and newlines so untrusted config
    values cannot break the table or the surrounding comment. Ordering is
    deterministic, so re-running on unchanged input yields byte-identical output.

    Args:
        diff: The pipeline diff to render.
        title: Optional heading text. When provided it is emitted as an ``##``
            heading above the summary; otherwise no heading is emitted.

    Returns:
        A Markdown string with no trailing newline.
    """
    org = _organize(diff)

    lines: List[str] = []
    if title:
        lines.append(f'## {title}')
        lines.append('')

    lines.append(f'**Pipeline diff:** {_summary_phrase(org)}')

    if not _any_output(org):
        return '\n'.join(lines)

    # --- Nodes ---
    provider_changed = [e for e in org['nodes_changed'] if e['has_provider_change']]
    if org['nodes_added'] or org['nodes_removed'] or provider_changed:
        lines.append('')
        lines.append('**Nodes**')
        for node_id, provider in org['nodes_added']:
            lines.append(f'- {_MD_ADDED} {_md_code(node_id)} ({_md_code(provider)})')
        for node_id, provider in org['nodes_removed']:
            lines.append(f'- {_MD_REMOVED} {_md_code(node_id)} ({_md_code(provider)})')
        for entry in provider_changed:
            lines.append(
                f'- {_MD_CHANGED} {_md_code(entry["id"])} provider: '
                f'{_md_code(entry["provider_old"])} → {_md_code(entry["provider_new"])}'
            )

    # --- Edges ---
    if org['edges_added'] or org['edges_removed']:
        lines.append('')
        lines.append('**Edges**')
        for from_id, lane, to_id in org['edges_added']:
            lines.append(f'- {_MD_ADDED} {_md_code(from_id)} --{_md_code(lane)}--> {_md_code(to_id)}')
        for from_id, lane, to_id in org['edges_removed']:
            lines.append(f'- {_MD_REMOVED} {_md_code(from_id)} --{_md_code(lane)}--> {_md_code(to_id)}')

    # --- Config (table) ---
    config_nodes = [e for e in org['nodes_changed'] if e['config_changes']]
    if config_nodes:
        lines.append('')
        lines.append('**Config**')
        lines.append('')
        lines.append('| Node | Field | Change |')
        lines.append('| --- | --- | --- |')
        for entry in config_nodes:
            for field_change in entry['config_changes']:
                node_cell = _md_cell(_md_code(entry['id']))
                field_cell = _md_cell(_md_code(field_change.path))
                change_cell = _md_cell(_md_field_change(field_change))
                lines.append(f'| {node_cell} | {field_cell} | {change_cell} |')

    # --- Version / Layout ---
    if org['version_change']:
        old = _md_code(_fmt_value(org['version_change'][0]))
        new = _md_code(_fmt_value(org['version_change'][1]))
        lines.append('')
        lines.append(f'**Version:** {old} → {new}')

    if org['layout_changed']:
        lines.append('')
        lines.append('_Layout (ui/viewport) changed._')

    return '\n'.join(lines)
