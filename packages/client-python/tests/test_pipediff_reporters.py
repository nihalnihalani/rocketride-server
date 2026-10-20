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
Tests for rocketride.pipediff.reporters.

Fixtures are built from the production ``rocketride.pipediff`` model classes, so
a change to the model (a new field, a renamed attribute) surfaces here instead of
being masked by a local mirror that drifts out of sync.

Coverage:
    - empty diff, layout-only diff, and a mixed diff for each renderer
    - human color on/off (ANSI escape presence)
    - control-character escaping in the human renderer
    - JSON document shape and summary contents
    - Markdown table escaping of ``|`` and backticks, and of the title/version
    - viewport enumeration under include_layout
    - deterministic ordering independent of engine emission order
"""

import html as html_mod
import json
import re
import unicodedata
import unittest
from html.parser import HTMLParser
from typing import Optional, Tuple

from rocketride.pipediff import EdgeChange, FieldChange, NodeChange, PipeDiff
from rocketride.pipediff.reporters import _md_cell, render_human, render_json, render_markdown

# CI installs cmarkgfm into the engine interpreter from tests/requirements.txt
# (the client-python:setup-test-deps step), so the renderer cross-check below
# runs there. The import stays guarded only so the rest of the module still
# collects on a local interpreter without it.
try:  # pragma: no cover - guarded for interpreters without the renderer
    import cmarkgfm
    from cmarkgfm.cmark import Options as CmarkOptions
except ImportError:  # pragma: no cover
    cmarkgfm = None
    CmarkOptions = None


def _mixed_diff() -> PipeDiff:
    """Build a representative diff touching every section."""
    return PipeDiff(
        node_changes=[
            NodeChange(id='qdrant_3', kind='added', provider_new='qdrant'),
            NodeChange(id='webhook_1', kind='removed', provider_old='webhook'),
            NodeChange(id='chat_1', kind='provider', provider_old='chat', provider_new='chat_v2'),
            NodeChange(
                id='preprocessor_langchain_1',
                kind='config',
                field_changes=[
                    FieldChange(path='config.default.strlen', kind='changed', old=512, new=1024),
                    FieldChange(path='config.parameters.top_p', kind='added', new=0.9),
                    FieldChange(path='config.mode', kind='removed', old='Source'),
                ],
            ),
        ],
        edge_changes=[
            EdgeChange(from_id='parse_1', lane='text', to_id='preprocessor_langchain_1', kind='added'),
            EdgeChange(from_id='webhook_1', lane='tags', to_id='parse_1', kind='removed'),
        ],
        version_change=(3, 4),
        layout_changed=False,
    )


def _render_gfm_row(table_markdown: str) -> Tuple[int, Optional[str]]:
    """
    Render a one-row GFM table and report ``(cell count, first code-span text)``.

    ``cmarkgfm`` wraps the same cmark-gfm that GitHub renders Markdown with, so
    this answers "what does a reviewer actually see" rather than reasoning about
    the parser. GFM discards excess cells, so a split row keeps its column
    count; what exposes a split is the last cell -- the value's code span is
    then truncated or gone, so the code-span text no longer equals the value.
    """
    html = cmarkgfm.github_flavored_markdown_to_html(table_markdown, options=CmarkOptions.CMARK_OPT_UNSAFE)
    body = re.search(r'<tbody>(.*?)</tbody>', html, re.S)
    cells = re.findall(r'<td[^>]*>(.*?)</td>', body.group(1) if body else '', re.S)
    code = re.search(r'<code>(.*?)</code>', cells[-1], re.S) if cells else None
    return len(cells), (html_mod.unescape(code.group(1)) if code else None)


class _GfmListItems(HTMLParser):
    """Read the visible list text and nesting from actual cmark-gfm output."""

    def __init__(self) -> None:
        super().__init__()
        self.items = []
        self._items = []
        self._depth = 0
        self.max_depth = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag == 'ul':
            self._depth += 1
            self.max_depth = max(self.max_depth, self._depth)
        elif tag == 'li':
            self._items.append([])

    def handle_data(self, data) -> None:
        if self._items:
            self._items[-1].append(data)

    def handle_endtag(self, tag) -> None:
        if tag == 'ul':
            self._depth -= 1
        elif tag == 'li':
            self.items.append(''.join(self._items.pop()).strip())


# Values whose escaping the two tests below both check: Windows paths and regex
# escapes (backslashes that must survive untouched), bare and pre-escaped pipes,
# and a run of both together.
_GFM_ESCAPING_CORPUS = [
    r'C:\Users\alice',
    'a|b',
    r'a\|b',
    r'a\\|b',
    r'\d+\|x',
    'a||b',
    'trailing-backslash\\',
    r'^\d{2}\|(a|b)$',
]


def _split_gfm_row(row: str) -> list:
    """
    Split a GFM table row into cells the way cmark-gfm's table scanner does.

    This is the library-free counterpart to ``_render_gfm_row``: it answers the
    only question ``_md_cell`` is responsible for -- does the row still have its
    columns, and does unescaping give the value back -- without needing a C
    extension that is not installed in CI.

    The rule, confirmed against cmark-gfm itself: a ``|`` splits the row only
    when no backslash immediately precedes it, and a ``|`` preceded by a run of
    *n* backslashes (*n* >= 1) is escaped and loses exactly one of them. Every
    other backslash is left alone, which is what makes a value like
    ``C:\\Users\\alice`` come through untouched. Cross-checked against
    ``cmarkgfm`` over several thousand random values built from the punctuation
    that appears in pipeline config: the two agree on every one.
    """
    row = row.strip()
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|'):
        row = row[:-1]
    cells: list = []
    current: list = []
    index = 0
    while index < len(row):
        if row[index] == '\\':
            run = 0
            while index < len(row) and row[index] == '\\':
                run += 1
                index += 1
            if index < len(row) and row[index] == '|':
                # The last backslash of the run pairs with the pipe: the pipe is
                # escaped (no split) and that one backslash is consumed.
                current.append('\\' * (run - 1))
                current.append('|')
                index += 1
            else:
                current.append('\\' * run)
            continue
        if row[index] == '|':
            cells.append(''.join(current))
            current = []
            index += 1
            continue
        current.append(row[index])
        index += 1
    cells.append(''.join(current))
    return cells


def _table_body_rows(markdown: str) -> list:
    """
    Return the data rows of every Markdown table in ``markdown``.

    Header rows and the ``| --- |`` separators are dropped, so a row count is a
    count of rendered changes. A row that a stray newline split in two shows up
    here as two rows, which is exactly what the escaping tests assert against.
    """
    rows = []
    in_body = False
    for line in markdown.splitlines():
        if not line.startswith('|'):
            in_body = False
            continue
        if set(line.replace('|', '').replace(' ', '')) == {'-'}:
            in_body = True
            continue
        if in_body:
            rows.append(line)
    return rows


class TestRenderHuman(unittest.TestCase):
    def test_empty_diff_reports_no_changes(self) -> None:
        self.assertEqual(render_human(PipeDiff(), use_color=False), 'No semantic changes.')

    def test_layout_only_is_not_no_changes(self) -> None:
        out = render_human(PipeDiff(layout_changed=True), use_color=False)
        self.assertNotEqual(out, 'No semantic changes.')
        self.assertIn('Layout', out)

    def test_mixed_sections_present(self) -> None:
        out = render_human(_mixed_diff(), use_color=False)
        self.assertIn('Nodes', out)
        self.assertIn('Edges', out)
        self.assertIn('Config', out)
        # Added / removed / provider-change / config markers.
        self.assertIn('+ qdrant_3 (qdrant)', out)
        self.assertIn('- webhook_1 (webhook)', out)
        self.assertIn('chat_1 provider: chat -> chat_v2', out)
        self.assertIn('+ parse_1 --text--> preprocessor_langchain_1', out)
        self.assertIn('- webhook_1 --tags--> parse_1', out)
        self.assertIn('~ config.default.strlen: 512 -> 1024', out)
        self.assertIn('Version: 3 -> 4', out)

    def test_no_color_has_no_ansi(self) -> None:
        out = render_human(_mixed_diff(), use_color=False)
        self.assertNotIn('\033', out)

    def test_color_emits_ansi(self) -> None:
        out = render_human(_mixed_diff(), use_color=True)
        self.assertIn('\033[', out)

    def test_no_trailing_newline(self) -> None:
        out = render_human(_mixed_diff(), use_color=False)
        self.assertFalse(out.endswith('\n'))

    def test_control_characters_in_values_are_escaped(self) -> None:
        # A .pipe file under review is untrusted input: a config value carrying
        # ANSI escapes could recolor or rewrite the report the reviewer reads.
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1\r\nfake line',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.msg', kind='changed', old='a', new='\x1b[31mred\x1b[0m'),
                    ],
                )
            ]
        )
        out = render_human(diff, use_color=False)
        self.assertNotIn('\x1b', out)
        self.assertNotIn('\r', out)
        # A value holding an escaped character is JSON-quoted, so its ESC reads as
        # JSON's escape; an id is not a JSON value and gets the terminal escape.
        self.assertIn('"\\u001b[31mred\\u001b[0m"', out)
        self.assertIn('\\x0d\\x0afake line', out)

    def test_control_characters_escaped_in_ids_lanes_and_version(self) -> None:
        diff = PipeDiff(
            node_changes=[NodeChange(id='a\x1b[2J', kind='added', provider_new='p\x1b[2J')],
            edge_changes=[EdgeChange(from_id='f\x1b[2J', lane='l\x1b[2J', to_id='t', kind='added')],
            version_change=('1', '2\x1b[2J'),
        )
        out = render_human(diff, use_color=False)
        self.assertNotIn('\x1b', out)
        self.assertIn('\\x1b[2J', out)

    def test_viewport_changes_render_as_layout_block(self) -> None:
        diff = PipeDiff(
            layout_changed=True,
            viewport_changes=[FieldChange(path='viewport.x', kind='changed', old=0, new=120)],
        )
        out = render_human(diff, use_color=False)
        self.assertIn('Layout', out)
        self.assertIn('viewport', out)
        self.assertIn('~ viewport.x: 0 -> 120', out)
        self.assertIn('1 viewport field changed', out)

    def test_c1_and_bidi_controls_are_escaped(self) -> None:
        # C1 controls (U+009B is an 8-bit CSI on terminals that honor C1) and the
        # Unicode bidi/isolate controls can reorder or spoof what the reviewer
        # reads, so they are escaped like the C0 controls.
        unsafe = ['\u009b', '\u0085', '\u061c', '\u200e', '\u200f', '\u2028', '\u2029']
        unsafe += [chr(code) for code in range(0x202A, 0x202F)] + [chr(code) for code in range(0x2066, 0x206A)]
        value = 'safe ' + ''.join(unsafe) + ' evil'
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.note', kind='changed', old='a', new=value)],
                )
            ],
            edge_changes=[EdgeChange(from_id='f\u202e', lane='l\u2066', to_id='t\u009b', kind='added')],
        )
        out = render_human(diff, use_color=False)
        for char in unsafe:
            self.assertNotIn(char, out)
        self.assertIn('\\x9b', out)
        self.assertIn('\\x85', out)
        self.assertIn('\\u202e', out)
        self.assertIn('\\u2066', out)
        self.assertIn('f\\u202e --l\\u2066--> t\\x9b', out)

    def test_escaped_control_and_literal_escape_text_stay_distinguishable(self) -> None:
        # U+202E and the six characters `\u202e` would both print as `\u202e` once
        # the control is escaped, so a value holding an escaped character is
        # JSON-quoted and the pair stays visibly different.
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.bidi', kind='changed', old='\u202e', new='\\u202e'),
                        FieldChange(path='config.esc', kind='changed', old='\\x1b', new='\x1b'),
                    ],
                )
            ]
        )
        out = render_human(diff, use_color=False)
        # A value holding an escaped character is JSON-quoted, so the real control
        # is quoted and the bare text of its escape is not.
        self.assertIn('~ config.bidi: "\\u202e" -> \\u202e', out)
        self.assertIn('~ config.esc: \\x1b -> "\\u001b"', out)
        self.assertNotIn('\u202e', out)
        self.assertNotIn('\x1b', out)

    def test_one_sided_values_that_read_as_other_json_are_quoted(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.a', kind='added', new='true'),
                        FieldChange(path='config.b', kind='added', new=True),
                        FieldChange(path='config.c', kind='added', new='""'),
                        FieldChange(path='config.d', kind='added', new=''),
                        FieldChange(path='config.e', kind='removed', old='512'),
                        FieldChange(path='config.f', kind='added', new='gpt-4 '),
                        FieldChange(path='config.g', kind='added', new='gpt-4'),
                    ],
                )
            ]
        )
        out = render_human(diff, use_color=False)
        self.assertIn('+ config.a = "true"', out)
        self.assertIn('+ config.b = true', out)
        self.assertIn('+ config.c = "\\"\\""', out)
        self.assertIn('+ config.d = ""', out)
        self.assertIn('- config.e = "512"', out)
        self.assertIn('+ config.f = "gpt-4 "', out)
        self.assertIn('+ config.g = gpt-4', out)

    def test_whitespace_only_changes_stay_visible(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.tab', kind='changed', old='a\tb', new='a b'),
                        FieldChange(path='config.pad', kind='changed', old='gpt-4', new=' gpt-4 '),
                    ],
                )
            ]
        )
        out = render_human(diff, use_color=False)
        self.assertIn('~ config.tab: "a\\tb" -> "a b"', out)
        # The padded side is quoted on its own, which already makes the edit visible.
        self.assertIn('~ config.pad: gpt-4 -> " gpt-4 "', out)

    def test_printable_non_ascii_is_left_alone(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.note', kind='changed', old='café', new='日本 → ok')],
                )
            ]
        )
        self.assertIn('~ config.note: café -> 日本 → ok', render_human(diff, use_color=False))

    def test_type_only_changes_render_distinguishably(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.n', kind='changed', old=512, new='512'),
                        FieldChange(path='config.flag', kind='changed', old=True, new='true'),
                        FieldChange(path='config.z', kind='changed', old=None, new='null'),
                        FieldChange(path='config.s', kind='changed', old='a', new='b'),
                        FieldChange(path='config.q', kind='changed', old='""', new=''),
                    ],
                )
            ],
            version_change=(1, '1'),
        )
        out = render_human(diff, use_color=False)
        self.assertIn('~ config.n: 512 -> "512"', out)
        self.assertIn('~ config.flag: true -> "true"', out)
        self.assertIn('~ config.z: null -> "null"', out)
        # Same-type string changes keep the compact bare rendering.
        self.assertIn('~ config.s: a -> b', out)
        self.assertIn('~ config.q: "\\"\\"" -> ""', out)
        self.assertIn('Version: 1 -> "1"', out)
        self.assertIn('version 1 → "1"', out.splitlines()[0])

    def test_empty_string_value_is_visible(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.note', kind='changed', old='', new='x'),
                        FieldChange(path='config.extra', kind='added', new=''),
                    ],
                )
            ]
        )
        out = render_human(diff, use_color=False)
        self.assertIn('~ config.note: "" -> x', out)
        self.assertIn('+ config.extra = ""', out)

    def test_provider_type_change_uses_json_spelling(self) -> None:
        diff = PipeDiff(node_changes=[NodeChange(id='n1', kind='provider', provider_old=0, provider_new=False)])
        self.assertIn('~ n1 provider: 0 -> false', render_human(diff, use_color=False))


class TestRenderJson(unittest.TestCase):
    def test_empty_diff_shape(self) -> None:
        doc = render_json(PipeDiff())
        self.assertEqual(set(doc.keys()), {'nodes', 'edges', 'viewport', 'summary'})
        self.assertEqual(set(doc['nodes'].keys()), {'added', 'removed', 'changed'})
        self.assertEqual(set(doc['edges'].keys()), {'added', 'removed'})
        self.assertEqual(doc['nodes']['added'], [])
        self.assertEqual(doc['edges']['removed'], [])
        self.assertEqual(doc['viewport'], [])
        self.assertFalse(doc['summary']['has_semantic_changes'])
        self.assertIsNone(doc['summary']['version_change'])
        self.assertFalse(doc['summary']['layout_changed'])
        self.assertEqual(doc['summary']['viewport_changes'], 0)

    def test_layout_only_summary(self) -> None:
        doc = render_json(PipeDiff(layout_changed=True))
        self.assertTrue(doc['summary']['layout_changed'])
        self.assertFalse(doc['summary']['has_semantic_changes'])

    def test_mixed_structure(self) -> None:
        doc = render_json(_mixed_diff())
        self.assertEqual(doc['nodes']['added'], [{'id': 'qdrant_3', 'provider': 'qdrant'}])
        self.assertEqual(doc['nodes']['removed'], [{'id': 'webhook_1', 'provider': 'webhook'}])

        # Two changed nodes: chat_1 (provider) and preprocessor (config).
        changed_by_id = {entry['id']: entry for entry in doc['nodes']['changed']}
        self.assertEqual(changed_by_id['chat_1']['provider_change'], {'old': 'chat', 'new': 'chat_v2'})
        self.assertEqual(changed_by_id['chat_1']['config_changes'], [])

        preprocessor = changed_by_id['preprocessor_langchain_1']
        self.assertIsNone(preprocessor['provider_change'])
        # config_changes deterministically sorted by (path, kind).
        paths = [fc['path'] for fc in preprocessor['config_changes']]
        self.assertEqual(paths, sorted(paths))
        for fc in preprocessor['config_changes']:
            self.assertEqual(set(fc.keys()), {'path', 'kind', 'old', 'new'})

        self.assertEqual(
            doc['edges']['added'],
            [{'from': 'parse_1', 'lane': 'text', 'to': 'preprocessor_langchain_1'}],
        )
        self.assertEqual(
            doc['edges']['removed'],
            [{'from': 'webhook_1', 'lane': 'tags', 'to': 'parse_1'}],
        )

        summary = doc['summary']
        self.assertEqual(summary['nodes_added'], 1)
        self.assertEqual(summary['nodes_removed'], 1)
        self.assertEqual(summary['nodes_changed'], 2)
        self.assertEqual(summary['edges_added'], 1)
        self.assertEqual(summary['edges_removed'], 1)
        self.assertEqual(summary['config_changes'], 3)
        self.assertEqual(summary['provider_changes'], 1)
        self.assertEqual(summary['version_change'], [3, 4])
        self.assertTrue(summary['has_semantic_changes'])

    def test_provider_and_config_on_same_id_merge(self) -> None:
        # Engine may emit provider + config as separate NodeChange records for the
        # same id; they must collapse into a single 'changed' entry.
        diff = PipeDiff(
            node_changes=[
                NodeChange(id='n1', kind='provider', provider_old='a', provider_new='b'),
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.x', kind='changed', old=1, new=2)],
                ),
            ]
        )
        doc = render_json(diff)
        self.assertEqual(len(doc['nodes']['changed']), 1)
        entry = doc['nodes']['changed'][0]
        self.assertEqual(entry['provider_change'], {'old': 'a', 'new': 'b'})
        self.assertEqual(len(entry['config_changes']), 1)

    def test_viewport_changes_are_enumerated_and_counted(self) -> None:
        diff = PipeDiff(
            layout_changed=True,
            viewport_changes=[
                FieldChange(path='viewport.zoom', kind='changed', old=1, new=2),
                FieldChange(path='viewport.x', kind='changed', old=0, new=120),
            ],
        )
        doc = render_json(diff)
        self.assertEqual([fc['path'] for fc in doc['viewport']], ['viewport.x', 'viewport.zoom'])
        self.assertEqual(doc['summary']['viewport_changes'], 2)
        self.assertTrue(doc['summary']['has_semantic_changes'])

    def test_json_serializable(self) -> None:
        # The document must round-trip through the json module unchanged.
        doc = render_json(_mixed_diff())
        self.assertEqual(json.loads(json.dumps(doc)), doc)


class TestRenderMarkdown(unittest.TestCase):
    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_node_add_remove_markers_survive_gfm_rendering(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(id='new_node', kind='added', provider_new='prompt'),
                NodeChange(id='old_node', kind='removed', provider_old='webhook'),
            ]
        )
        parsed = _GfmListItems()
        parsed.feed(cmarkgfm.github_flavored_markdown_to_html(render_markdown(diff)))
        self.assertEqual(parsed.items, ['+ new_node (prompt)', '- old_node (webhook)'])
        self.assertEqual(parsed.max_depth, 1)

    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_edge_add_remove_markers_survive_gfm_rendering(self) -> None:
        diff = PipeDiff(
            edge_changes=[
                EdgeChange(from_id='new_source', lane='text', to_id='target', kind='added'),
                EdgeChange(from_id='old_source', lane='control', to_id='target', kind='removed'),
            ]
        )
        parsed = _GfmListItems()
        parsed.feed(cmarkgfm.github_flavored_markdown_to_html(render_markdown(diff)))
        self.assertEqual(parsed.items, ['+ new_source --text--> target', '- old_source --control--> target'])
        self.assertEqual(parsed.max_depth, 1)

    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_empty_string_value_cannot_break_out_of_its_code_span(self) -> None:
        # An empty value used to render as a bare double backtick, which GFM pairs
        # with the next value's two-backtick fence: the arrow became the code span
        # and the rest of the untrusted value rendered as live Markdown.
        hostile = 'x` [click](https://example.invalid/p) @someone ![i](https://example.invalid/i.png) **bold**'
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.note', kind='changed', old='', new=hostile)],
                ),
                NodeChange(id='n2', kind='provider', provider_old='', provider_new=hostile),
            ],
            version_change=('', hostile),
        )
        out = render_markdown(diff)
        html = cmarkgfm.github_flavored_markdown_to_html(out)
        for tag in ('<a ', '<img', '<strong>bold'):
            self.assertNotIn(tag, html)
        # The empty side is shown as a visible JSON empty string.
        self.assertIn('<code>&quot;&quot;</code> → <code>x` [click]', html)
        self.assertIn('**Version:** `""` →', out)

    def test_values_that_render_alike_in_markdown_stay_distinguishable(self) -> None:
        # `a\nb` and `a b` used to render the same in Markdown.
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.s', kind='changed', old='a\nb', new='a b')],
                ),
                NodeChange(id='n2', kind='provider', provider_old='p\nq', provider_new='p q'),
            ],
            version_change=('1\n2', '1 2'),
        )
        out = render_markdown(diff)
        # A value holding a line break is JSON-quoted in every Markdown location, so
        # it never reads like the same text with a space.
        self.assertIn('| `n1` | `config.s` | `"a\\nb"` → `a b` |', out)
        self.assertIn('- ~ `n2` provider: `"p\\nq"` → `p q`', out)
        self.assertIn('**Version:** `"1\\n2"` → `1 2`', out)

    # Each value differs from the plain one only by a character a reader cannot see:
    # a zero-width space or joiner, a word joiner, a BOM, a soft hyphen, a tag
    # character, or a space other than U+0020.
    _LOOKALIKES = [
        ('openai', 'open\u200bai'),
        ('ab', 'a\u200db'),
        ('ab', 'a\u2060b'),
        ('ab', 'a\ufeffb'),
        ('ab', 'a\u00adb'),
        ('ab', 'a\U000e0041b'),
        ('a b', 'a\u00a0b'),
        ('a b', 'a\u3000b'),
        # Just as invisible, but not format characters or spaces by category.
        ('ab', 'a\u034fb'),
        ('ab', 'a\ufe0fb'),
        ('ab', 'a\U000e0100b'),
        ('ab', 'a\u180bb'),
        ('ab', 'a\u3164b'),
        ('ab', 'a\u2800b'),
    ]

    def test_invisible_and_lookalike_characters_are_escaped(self) -> None:
        """A change hidden in an invisible character must show in both reports."""
        for old, new in self._LOOKALIKES:
            with self.subTest(new=new.encode('unicode_escape').decode()):
                diff = PipeDiff(
                    node_changes=[
                        NodeChange(
                            id='n1',
                            kind='config',
                            field_changes=[FieldChange(path='config.v', kind='changed', old=old, new=new)],
                        ),
                        NodeChange(id=new, kind='added', provider_new=new),
                    ]
                )
                (hidden,) = [char for char in new if char not in old]
                code = ord(hidden)
                escape = (
                    f'\\x{code:02x}' if code <= 0xFF else (f'\\u{code:04x}' if code <= 0xFFFF else f'\\U{code:08x}')
                )
                for out in (render_markdown(diff), render_human(diff, use_color=False)):
                    self.assertNotIn(hidden, out)
                    self.assertIn(escape, out)

    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_invisible_characters_render_differently_on_github(self) -> None:
        """Checked through cmark-gfm: the two sides of each change render as different text."""
        for old, new in self._LOOKALIKES:
            with self.subTest(new=new.encode('unicode_escape').decode()):
                diff = PipeDiff(
                    node_changes=[
                        NodeChange(
                            id='n1',
                            kind='config',
                            field_changes=[FieldChange(path='config.v', kind='changed', old=old, new=new)],
                        )
                    ]
                )
                html = cmarkgfm.github_flavored_markdown_to_html(render_markdown(diff))
                spans = re.findall(r'<code>(.*?)</code>', html)
                change = spans[-2:]
                self.assertEqual(len(change), 2, html)
                self.assertNotEqual(' '.join(change[0].split()), ' '.join(change[1].split()), html)

    def test_one_sided_values_keep_escapes_and_their_text_apart(self) -> None:
        """An added real control and an added text of its escape must not print alike."""
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.real', kind='added', new='\u202e'),
                        FieldChange(path='config.text', kind='added', new='\\u202e'),
                        FieldChange(path='config.esc', kind='removed', old='\x1b'),
                        FieldChange(path='config.esc_text', kind='removed', old='\\x1b'),
                        FieldChange(path='config.newline', kind='added', new='a\nb'),
                        FieldChange(path='config.space', kind='added', new='a b'),
                    ],
                )
            ]
        )
        md = render_markdown(diff)
        self.assertIn('| `n1` | `config.real` | + `"\\u202e"` |', md)
        self.assertIn('| `n1` | `config.text` | + `\\u202e` |', md)
        self.assertIn('| `n1` | `config.esc` | - `"\\u001b"` |', md)
        self.assertIn('| `n1` | `config.esc_text` | - `\\x1b` |', md)
        self.assertIn('| `n1` | `config.newline` | + `"a\\nb"` |', md)
        self.assertIn('| `n1` | `config.space` | + `a b` |', md)
        human = render_human(diff, use_color=False)
        self.assertIn('+ config.real = "\\u202e"', human)
        self.assertIn('+ config.text = \\u202e', human)
        self.assertIn('- config.esc = "\\u001b"', human)
        self.assertIn('- config.esc_text = \\x1b', human)

    def test_a_lone_surrogate_is_escaped_rather_than_breaking_output(self) -> None:
        """JSON's ``"\\ud800"`` decodes to a lone surrogate, which no UTF-8 stream can carry."""
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n\ud800',
                    kind='config',
                    field_changes=[FieldChange(path='config.v', kind='changed', old='a', new='\udfff')],
                )
            ]
        )
        for out in (render_markdown(diff), render_human(diff, use_color=False)):
            out.encode('utf-8')
            self.assertIn('\\ud800', out)
            self.assertIn('\\udfff', out)

    def test_control_and_bidi_characters_are_escaped_in_markdown(self) -> None:
        # The Markdown report is auto-posted as a PR comment; a bidi override in a
        # value or id would visually reorder the diff a reviewer reads there.
        unsafe = ['\u202e', '\u2066', '\u200f', '\u2028', '\u009b', '\x1b']
        diff = PipeDiff(
            node_changes=[
                NodeChange(id='n\u202e1', kind='added', provider_new='p\u2066'),
                NodeChange(
                    id='n2',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.v', kind='changed', old='a', new='safe ' + ''.join(unsafe) + ' evil')
                    ],
                ),
            ],
            version_change=('1', '2\u200f'),
        )
        out = render_markdown(diff, title='flow\u202e.pipe')
        for char in unsafe:
            self.assertNotIn(char, out)
        self.assertIn('`n\\u202e1`', out)
        self.assertIn('\\u2066', out)
        self.assertIn('\\u001b', out)
        self.assertIn('\\x9b', out)

    def test_markdown_pairs_compare_what_github_renders(self) -> None:
        # A code span drops one leading and trailing space, so `gpt-4` and
        # ` gpt-4 ` render alike unless the pair is quoted.
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[FieldChange(path='config.m', kind='changed', old='gpt-4', new=' gpt-4 ')],
                )
            ]
        )
        self.assertIn('| `n1` | `config.m` | `gpt-4` → `" gpt-4 "` |', render_markdown(diff))

    def test_reporter_source_has_no_raw_invisible_characters(self) -> None:
        import rocketride.pipediff.reporters as reporters_module

        with open(reporters_module.__file__, encoding='utf-8') as handle:
            source = handle.read()
        hidden = sorted({f'U+{ord(c):04X}' for c in source if unicodedata.category(c) in ('Cf', 'Zl', 'Zp')})
        self.assertEqual(hidden, [])

    def test_md_code_never_emits_an_empty_code_span(self) -> None:
        from rocketride.pipediff.reporters import _md_code

        self.assertEqual(_md_code(''), '`""`')

    def test_values_use_json_spelling(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.flag', kind='changed', old=True, new='true'),
                        FieldChange(path='config.n', kind='changed', old=512, new='512'),
                        FieldChange(path='config.z', kind='removed', old=None),
                        FieldChange(path='config.claude', kind='added', new={'apikey': 'x'}),
                        FieldChange(path='config.on', kind='changed', old=True, new=False),
                    ],
                )
            ]
        )
        out = render_markdown(diff)
        self.assertIn('| `config.flag` | `true` → `"true"` |', out)
        self.assertIn('| `config.n` | `512` → `"512"` |', out)
        self.assertIn('| `config.z` | - `null` |', out)
        self.assertIn('| `config.claude` | + `{"apikey": "x"}` |', out)
        self.assertIn('| `config.on` | `true` → `false` |', out)
        self.assertNotIn('True', out)
        self.assertNotIn('None', out)

    def test_empty_diff_summary(self) -> None:
        out = render_markdown(PipeDiff())
        self.assertIn('no semantic changes', out)
        self.assertNotIn('**Nodes**', out)
        self.assertNotIn('**Edges**', out)

    def test_title_heading(self) -> None:
        out = render_markdown(PipeDiff(), title='pipeline.pipe')
        self.assertTrue(out.startswith('## `pipeline.pipe`'))

    def test_title_with_newline_cannot_inject_markdown(self) -> None:
        # The action passes a repository file path as the title; a path is
        # attacker-controlled content in a fork PR.
        out = render_markdown(PipeDiff(), title='a.pipe\n\n## INJECTED\n\n@everyone')
        for line in out.splitlines():
            self.assertFalse(line.lstrip().startswith('## INJECTED'), line)
            self.assertFalse(line.lstrip().startswith('@everyone'), line)

    def test_version_in_summary_line_is_code_spanned(self) -> None:
        # The summary line interpolates the two `version` values; in Markdown they
        # must be code-spanned or a crafted version breaks out of the comment.
        out = render_markdown(PipeDiff(version_change=('1', '2`\n\n# pwned')))
        summary_line = out.splitlines()[0]
        self.assertIn('**Pipeline diff:**', summary_line)
        self.assertNotIn('\n\n#', out)
        for line in out.splitlines():
            self.assertFalse(line.lstrip().startswith('# pwned'), line)

    def test_viewport_changes_render_as_layout_table(self) -> None:
        diff = PipeDiff(
            layout_changed=True,
            viewport_changes=[FieldChange(path='viewport.x', kind='changed', old=0, new=120)],
        )
        out = render_markdown(diff)
        self.assertIn('**Layout**', out)
        self.assertIn('| Field | Change |', out)
        self.assertIn('`viewport.x`', out)

    def test_mixed_sections(self) -> None:
        out = render_markdown(_mixed_diff())
        self.assertIn('**Pipeline diff:**', out)
        self.assertIn('**Nodes**', out)
        self.assertIn('**Edges**', out)
        self.assertIn('**Config**', out)
        self.assertIn('| Node | Field | Change |', out)
        self.assertIn('`qdrant_3`', out)
        self.assertIn('**Version:**', out)

    def test_layout_only(self) -> None:
        out = render_markdown(PipeDiff(layout_changed=True))
        self.assertIn('Layout', out)

    def test_newlines_in_untrusted_values_cannot_break_out(self) -> None:
        # A .pipe file is untrusted PR content, and render_markdown output is
        # dumped verbatim into an auto-posted sticky PR comment. A newline in a
        # provider/lane/id/config value must not terminate its code span and let
        # the trailing text render as real Markdown (headings, @-mentions, etc.).
        payload = 'x\n\n## INJECTED HEADING\n\n@everyone please approve'
        diff = PipeDiff(
            node_changes=[
                NodeChange(id='n1', kind='added', provider_new=payload),
                NodeChange(
                    id='n2\n\n### id-inject',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.p\n\n### path-inject', kind='changed', old='a\r\nb', new=payload),
                    ],
                ),
            ],
            edge_changes=[
                EdgeChange(from_id='a', lane='l\n\n### lane-inject', to_id='b', kind='added'),
            ],
        )
        out = render_markdown(diff, title='rag.pipe')
        # The injected content must never break out of its code span onto its own
        # line — that is what would make '## INJECTED HEADING' render as a real
        # heading. Every injected marker must survive only inline inside a span,
        # never at the start of a line, and no attacker-introduced blank line may
        # appear before a heading.
        self.assertNotIn('\n\n#', out)
        for line in out.splitlines():
            self.assertFalse(line.lstrip().startswith('## INJECTED'), line)
            self.assertFalse(line.lstrip().startswith('### '), line)
            self.assertFalse(line.lstrip().startswith('@everyone'), line)
        # Carriage returns are neutralized too (a lone \r can also break rows).
        self.assertNotIn('\r', out)

    def test_table_escapes_pipe_and_backtick(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.template', kind='changed', old='a|b', new='x`y'),
                    ],
                )
            ]
        )
        out = render_markdown(diff)
        # The literal pipe from the value must be escaped inside the table cell.
        self.assertIn('\\|', out)
        self.assertNotIn('a|b', out)
        # A backtick inside a value forces a longer code fence.
        self.assertIn('``', out)
        # Every table body row must have balanced, escaped columns (no stray bar).
        table_rows = [ln for ln in out.splitlines() if ln.startswith('| ') and '---' not in ln]
        for row in table_rows:
            # Unescaped pipes only appear as the 4 column delimiters.
            unescaped = row.replace('\\|', '')
            self.assertEqual(unescaped.count('|'), 4, row)

    def test_table_does_not_double_backslashes_in_code_spans(self) -> None:
        """
        Backslashes inside a table cell must survive verbatim.

        Every value reaching a cell is already wrapped in a code span, and a
        code span does no backslash unescaping — so the cell escaper used to
        double them and ``C:\\Users\\alice`` rendered as ``C:\\\\Users\\\\alice``.
        Only ``\\|`` is meaningful to GitHub's table parser, and that escape
        stays.

        A backslash sitting immediately before a pipe is **not** a special case:
        the value ``\\d+\\|x`` is emitted as ``\\d+\\\\|x``, one added backslash
        and no more. See
        :meth:`test_md_cell_adds_exactly_one_backslash_per_pipe` for the full
        matrix and the cmark-gfm round-trip that pins why.
        """
        windows_path = r'C:\Users\alice'
        regex_value = r'\d+\|x'
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.out_dir', kind='changed', old='/tmp', new=windows_path),
                        FieldChange(path='config.pattern', kind='added', new=regex_value),
                    ],
                )
            ]
        )
        out = render_markdown(diff)

        # Backslashes appear exactly as authored, never doubled.
        self.assertIn(windows_path, out)
        self.assertNotIn(r'C:\\Users', out)
        # The regex keeps its single backslashes; only its pipe gains an escape.
        self.assertIn(r'`\d+\\|x`', out)
        self.assertNotIn(r'\\d+', out)

        rows = _table_body_rows(out)
        self.assertEqual(len(rows), 2, out)
        for row in rows:
            # Pipes from the values are escaped, so only the 4 delimiters remain.
            self.assertEqual(row.replace('\\|', '').count('|'), 4, row)

    def test_md_cell_adds_exactly_one_backslash_per_pipe(self) -> None:
        """
        Pin the exact bytes ``_md_cell`` emits, including backslash-before-pipe.

        cmark-gfm's table-cell scanner accepts either a lone backslash or a
        backslash-escaped punctuation pair and takes the longest match, so a run
        of *n* backslashes before a pipe parses as *n - 1* lone backslashes plus
        the escaped pair ``\\|``: the pipe is escaped for every *n* >= 1 and the
        row never splits. Unescaping strips exactly that one backslash. Adding
        one is therefore both necessary and sufficient — doubling the run would
        render a spurious extra backslash rather than protect anything.
        """
        cases = [
            # (value, exact text _md_cell must emit)
            (r'C:\Users\alice', r'C:\Users\alice'),  # no pipe -> untouched
            ('a|b', r'a\|b'),
            (r'a\|b', r'a\\|b'),
            (r'a\\|b', r'a\\\|b'),
            (r'\d+\|x', r'\d+\\|x'),
            ('a||b', r'a\|\|b'),
            ('trailing-backslash\\', 'trailing-backslash\\'),  # no pipe -> untouched
            ('a\nb', 'a b'),
            ('a\nb|c', r'a b\|c'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_md_cell(value), expected)

    def test_escaped_cells_survive_gfm_row_splitting(self) -> None:
        """
        Every escaped value must keep the row at three columns and unescape back
        to itself.

        Same corpus as the ``cmarkgfm`` cross-check below, but resolved with
        ``_split_gfm_row`` so it runs everywhere -- including on an interpreter
        that has no ``cmarkgfm`` at all. CI installs the renderer into the engine
        interpreter from tests/requirements.txt, so both checks run there; this
        one is the fallback for a local interpreter, not the one that settles the
        rule. A row that split shows up here as more than three cells.
        """
        for value in _GFM_ESCAPING_CORPUS:
            with self.subTest(value=value):
                row = f'| n1 | `config.v` | `{_md_cell(value)}` |'
                cells = _split_gfm_row(row)
                self.assertEqual(len(cells), 3, f'row split by GFM: {row!r}')
                self.assertEqual(cells[2].strip(), f'`{value}`', f'cell does not unescape to the value: {row!r}')

    @unittest.skipIf(
        cmarkgfm is None,
        'cmarkgfm is not installed; CI installs it from tests/requirements.txt so this runs there, '
        'and a local interpreter can get it with `pip install .[test]` -- the library-free check above '
        'covers the same corpus meanwhile',
    )
    def test_gfm_renders_escaped_cells_back_to_the_original_value(self) -> None:
        """
        Render the escaped cells through GFM and check what a reader actually sees.

        This is the test that decides the backslash question rather than arguing
        it: for each value, the emitted row must keep its three columns and the
        code span must contain the original value, byte for byte. It is not
        optional in CI -- tests/requirements.txt installs ``cmarkgfm`` into the
        engine interpreter the suite runs on, so this executes rather than skips.
        """
        for value in _GFM_ESCAPING_CORPUS:
            with self.subTest(value=value):
                row = f'| n1 | `config.v` | `{_md_cell(value)}` |'
                table = '| Node | Field | Change |\n| --- | --- | --- |\n' + row + '\n'
                cells, code = _render_gfm_row(table)
                self.assertEqual(cells, 3, f'unexpected column count: {row!r}')
                self.assertIsNotNone(code, f'row split by GFM (code span truncated): {row!r}')
                self.assertEqual(code, value, f'rendered cell differs from the value: {row!r}')

    def test_table_cell_neutralizes_newlines_without_touching_backslashes(self) -> None:
        """A newline in a value must not break the row, and must not cost a backslash."""
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n1',
                    kind='config',
                    field_changes=[
                        FieldChange(
                            path='config.script',
                            kind='changed',
                            old='a\nb',
                            new='C:\\tmp\nnext|line',
                        ),
                    ],
                )
            ]
        )
        out = render_markdown(diff)

        rows = _table_body_rows(out)
        self.assertEqual(len(rows), 1, out)
        row = rows[0]
        # One row means the embedded newlines were neutralized, not passed through:
        # each value holds a newline, so it is JSON-quoted and the newline reads as
        # JSON's `\n`. The only doubled backslash is JSON's own; the cell adds none.
        self.assertIn('`"a\\nb"`', row)
        self.assertIn('`"C:\\\\tmp\\nnext\\|line"`', row)
        self.assertNotIn('C:\\\\\\tmp', row)
        self.assertEqual(row.replace('\\|', '').count('|'), 4, row)


# Pairs of spellings that Unicode treats as the same text, written by name because a
# literal would be rewritten by any editor that normalises. Each pair prints alike
# unless the unnormalised side is spelled out: ``(label, composed, unnormalised)``.
_EQUIVALENT_SPELLINGS = [
    ('accent', 'caf\N{LATIN SMALL LETTER E WITH ACUTE}', 'cafe\N{COMBINING ACUTE ACCENT}'),
    ('ring', '\N{LATIN CAPITAL LETTER A WITH RING ABOVE}', 'A\N{COMBINING RING ABOVE}'),
    (
        'stacked marks',
        '\N{LATIN SMALL LETTER A WITH CIRCUMFLEX AND ACUTE}',
        'a\N{COMBINING CIRCUMFLEX ACCENT}\N{COMBINING ACUTE ACCENT}',
    ),
    ('angstrom sign', '\N{LATIN CAPITAL LETTER A WITH RING ABOVE}', '\N{ANGSTROM SIGN}'),
    ('ohm sign', '\N{GREEK CAPITAL LETTER OMEGA}', '\N{OHM SIGN}'),
    ('hangul', '\N{HANGUL SYLLABLE GA}', '\N{HANGUL CHOSEONG KIYEOK}\N{HANGUL JUNGSEONG A}'),
    ('kana', '\N{HIRAGANA LETTER GA}', '\N{HIRAGANA LETTER KA}\N{COMBINING KATAKANA-HIRAGANA VOICED SOUND MARK}'),
]

# Compatibility look-alikes: not rewritten by NFC, so they stay readable where a value
# is shown alone, and are separated only where both sides of a change are shown.
_COMPATIBILITY_LOOKALIKES = [
    ('full-width digit', 'gpt-4', 'gpt-\N{FULLWIDTH DIGIT FOUR}'),
    ('ligature', 'fi', '\N{LATIN SMALL LIGATURE FI}'),
    ('superscript', 'x2', 'x\N{SUPERSCRIPT TWO}'),
]


def _reader_view(text: str) -> str:
    """What a reader can tell apart: compatibility forms folded, whitespace runs collapsed."""
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def _github_code_spans(markdown: str) -> list:
    """The text of every code span cmark-gfm renders from ``markdown``, in order."""
    html = cmarkgfm.github_flavored_markdown_to_html(markdown, options=CmarkOptions.CMARK_OPT_UNSAFE)
    return [html_mod.unescape(span) for span in re.findall(r'<code>(.*?)</code>', html, re.S)]


# Where one piece of text can appear on its own in a report, each as a diff holding only that text.
_ALONE = {
    'added node id': lambda t: PipeDiff(node_changes=[NodeChange(id=t, kind='added', provider_new='p')]),
    'removed node id': lambda t: PipeDiff(node_changes=[NodeChange(id=t, kind='removed', provider_old='p')]),
    'node provider': lambda t: PipeDiff(node_changes=[NodeChange(id='n', kind='added', provider_new=t)]),
    'edge endpoints and lane': lambda t: PipeDiff(edge_changes=[EdgeChange(from_id=t, lane=t, to_id=t, kind='added')]),
    'config path': lambda t: PipeDiff(
        node_changes=[
            NodeChange(id='n', kind='config', field_changes=[FieldChange(path='config.' + t, kind='added', new=1)])
        ]
    ),
    'added value': lambda t: PipeDiff(
        node_changes=[
            NodeChange(id='n', kind='config', field_changes=[FieldChange(path='config.v', kind='added', new=t)])
        ]
    ),
    'removed value': lambda t: PipeDiff(
        node_changes=[
            NodeChange(id='n', kind='config', field_changes=[FieldChange(path='config.v', kind='removed', old=t)])
        ]
    ),
    'viewport path': lambda t: PipeDiff(
        viewport_changes=[FieldChange(path='viewport.' + t, kind='added', new=1)], layout_changed=True
    ),
}

# Where both sides of a change are shown together: ``(diff of a -> b, pattern for the human line)``.
_PAIRED = {
    'changed value': (
        lambda a, b: PipeDiff(
            node_changes=[
                NodeChange(
                    id='n', kind='config', field_changes=[FieldChange(path='config.v', kind='changed', old=a, new=b)]
                )
            ]
        ),
        r'^    ~ config\.v: (.*) -> (.*)$',
    ),
    'provider change': (
        lambda a, b: PipeDiff(node_changes=[NodeChange(id='n', kind='provider', provider_old=a, provider_new=b)]),
        r'^  ~ n provider: (.*) -> (.*)$',
    ),
    'version': (lambda a, b: PipeDiff(version_change=(a, b)), r'^Version: (.*) -> (.*)$'),
}


class TestEquivalentSpellings(unittest.TestCase):
    """Text that Unicode treats as equal, but that differs in the file, must differ in the report."""

    def test_unnormalised_text_is_spelled_out_wherever_it_can_appear(self) -> None:
        for label, composed, unnormalised in _EQUIVALENT_SPELLINGS:
            for place, build in _ALONE.items():
                with self.subTest(spelling=label, place=place):
                    composed_human = render_human(build(composed), use_color=False)
                    plain_human = render_human(build(unnormalised), use_color=False)
                    # The composed spelling is ordinary printable text and stays readable.
                    self.assertIn(composed, composed_human)
                    self.assertIn(composed, render_markdown(build(composed)))
                    # The other one never reaches the page raw, so the two cannot read alike.
                    for report in (plain_human, render_markdown(build(unnormalised))):
                        self.assertNotIn(unnormalised, report)
                        self.assertIn('\\u', report)
                    self.assertNotEqual(_reader_view(composed_human), _reader_view(plain_human))

    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_unnormalised_text_differs_in_the_markdown_github_renders(self) -> None:
        for label, composed, unnormalised in _EQUIVALENT_SPELLINGS:
            for place, build in _ALONE.items():
                with self.subTest(spelling=label, place=place):
                    shown = _github_code_spans(render_markdown(build(composed)))
                    other = _github_code_spans(render_markdown(build(unnormalised)))
                    self.assertEqual(len(shown), len(other))
                    self.assertNotEqual([_reader_view(s) for s in shown], [_reader_view(s) for s in other])
            with self.subTest(spelling=label, place='title'):
                title = _github_code_spans(render_markdown(PipeDiff(), title=composed))[0]
                other = _github_code_spans(render_markdown(PipeDiff(), title=unnormalised))[0]
                self.assertNotEqual(_reader_view(title), _reader_view(other))

    def test_both_sides_of_a_change_never_read_alike_in_the_terminal(self) -> None:
        for label, composed, unnormalised in _EQUIVALENT_SPELLINGS + _COMPATIBILITY_LOOKALIKES:
            for place, (build, pattern) in _PAIRED.items():
                for old, new in ((composed, unnormalised), (unnormalised, composed)):
                    with self.subTest(spelling=label, place=place, old=old.encode('unicode_escape')):
                        match = re.search(pattern, render_human(build(old, new), use_color=False), re.M)
                        self.assertIsNotNone(match)
                        self.assertNotEqual(_reader_view(match.group(1)), _reader_view(match.group(2)))

    @unittest.skipIf(cmarkgfm is None, 'cmarkgfm is not installed')
    def test_both_sides_of_a_change_never_read_alike_in_the_markdown_github_renders(self) -> None:
        for label, composed, unnormalised in _EQUIVALENT_SPELLINGS + _COMPATIBILITY_LOOKALIKES:
            for place, (build, _pattern) in _PAIRED.items():
                for old, new in ((composed, unnormalised), (unnormalised, composed)):
                    with self.subTest(spelling=label, place=place, old=old.encode('unicode_escape')):
                        # The last two code spans of the report are the old and the new side.
                        before, after = _github_code_spans(render_markdown(build(old, new)))[-2:]
                        self.assertNotEqual(_reader_view(before), _reader_view(after))

    def test_compatibility_lookalikes_are_spelled_out_only_when_they_collide(self) -> None:
        for label, plain, lookalike in _COMPATIBILITY_LOOKALIKES:
            with self.subTest(spelling=label):
                changed = PipeDiff(
                    node_changes=[
                        NodeChange(
                            id='n',
                            kind='config',
                            field_changes=[
                                FieldChange(path='config.v', kind='changed', old=plain, new=lookalike),
                                FieldChange(path='config.w', kind='changed', old='a', new=lookalike),
                            ],
                        )
                    ]
                )
                human = render_human(changed, use_color=False)
                # Alike to a reader: both quoted, the look-alike written as an escape.
                self.assertIn(f'~ config.v: "{plain}" -> "', human)
                self.assertNotIn(lookalike, human.split('config.w')[0])
                # Not alike: compact and readable, as before.
                self.assertIn(f'~ config.w: a -> {lookalike}', human)

    def test_normalised_non_ascii_text_is_left_readable(self) -> None:
        text = (
            'caf\N{LATIN SMALL LETTER E WITH ACUTE} \N{HIRAGANA LETTER GA}\N{HIRAGANA LETTER KI} \N{HANGUL SYLLABLE GA}'
        )
        diff = PipeDiff(
            node_changes=[
                NodeChange(id=text, kind='added', provider_new=text),
                NodeChange(id='n', kind='config', field_changes=[FieldChange(path='config.v', kind='added', new=text)]),
            ]
        )
        for report in (render_human(diff, use_color=False), render_markdown(diff)):
            self.assertNotIn('\\u', report)
            self.assertIn(text, report)

    def test_one_unnormalised_word_does_not_hide_the_rest_of_an_ascii_sentence(self) -> None:
        text = 'use the cafe\N{COMBINING ACUTE ACCENT} model, not the cafe model'
        diff = PipeDiff(
            node_changes=[
                NodeChange(id='n', kind='config', field_changes=[FieldChange(path='config.v', kind='added', new=text)])
            ]
        )
        self.assertIn('"use the cafe\\u0301 model, not the cafe model"', render_human(diff, use_color=False))

    def test_a_real_combining_mark_and_the_text_of_its_escape_stay_apart(self) -> None:
        diff = PipeDiff(
            node_changes=[
                NodeChange(
                    id='n',
                    kind='config',
                    field_changes=[
                        FieldChange(
                            path='config.v',
                            kind='changed',
                            old='e\N{COMBINING ACUTE ACCENT}',
                            new='e' + chr(92) + 'u0301',
                        )
                    ],
                )
            ]
        )
        self.assertIn(
            '~ config.v: "e' + chr(92) + 'u0301" -> e' + chr(92) + 'u0301', render_human(diff, use_color=False)
        )


class TestDeterminism(unittest.TestCase):
    def _scrambled_diff(self) -> PipeDiff:
        """Same logical changes as _mixed_diff but emitted in a different order."""
        return PipeDiff(
            node_changes=[
                NodeChange(
                    id='preprocessor_langchain_1',
                    kind='config',
                    field_changes=[
                        FieldChange(path='config.mode', kind='removed', old='Source'),
                        FieldChange(path='config.parameters.top_p', kind='added', new=0.9),
                        FieldChange(path='config.default.strlen', kind='changed', old=512, new=1024),
                    ],
                ),
                NodeChange(id='chat_1', kind='provider', provider_old='chat', provider_new='chat_v2'),
                NodeChange(id='webhook_1', kind='removed', provider_old='webhook'),
                NodeChange(id='qdrant_3', kind='added', provider_new='qdrant'),
            ],
            edge_changes=[
                EdgeChange(from_id='webhook_1', lane='tags', to_id='parse_1', kind='removed'),
                EdgeChange(from_id='parse_1', lane='text', to_id='preprocessor_langchain_1', kind='added'),
            ],
            version_change=(3, 4),
            layout_changed=False,
        )

    def test_human_is_order_independent(self) -> None:
        self.assertEqual(
            render_human(_mixed_diff(), use_color=False),
            render_human(self._scrambled_diff(), use_color=False),
        )

    def test_json_is_order_independent(self) -> None:
        self.assertEqual(render_json(_mixed_diff()), render_json(self._scrambled_diff()))

    def test_markdown_is_order_independent(self) -> None:
        self.assertEqual(render_markdown(_mixed_diff()), render_markdown(self._scrambled_diff()))


if __name__ == '__main__':
    unittest.main()
