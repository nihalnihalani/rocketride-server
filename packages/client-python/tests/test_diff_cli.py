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
Tests for the ``rocketride diff`` CLI subcommand (rocketride.cli.commands.diff).

These exercise ``run_diff`` end-to-end against real ``.pipe`` files on disk,
driving it through the same pinned engine and reporters the CLI uses in
production. The command is fully local (no server, no auth), so no client fixture
or network mock is needed; the only external dependency stubbed here is
``resolve_git_ref`` for ``--git`` mode, patched in the command's own module
namespace the same way the engine test suite stubs subprocess. Nesting-error
regressions additionally execute real CLI subprocesses against real files and
temporary Git history, without mocking the failing load/compare/render path.

Coverage mirrors the product contract:
    - two-file happy path (semantic changes -> exit 1)
    - identical files (-> exit 0, "No semantic changes.")
    - ``--git`` mode with a mocked resolver (found ref, and file-absent -> all added)
    - unreadable / unparseable / non-pipe input (-> exit 2, error on stderr)
    - argument-usage errors (wrong file count for the mode -> exit 2)
    - ``--json`` output purity (stdout is a single parseable document)
    - ``--markdown`` output
    - ``--include-layout`` toggling ui.* field lines and the exit code
    - ``--exit-zero`` forcing 0 on changes but never masking an error
    - argparse registration + dispatch: 'diff' exists, routes to ``run_diff``,
      takes no connection args, and makes ``--json``/``--markdown`` mutually
      exclusive
"""

import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rocketride.cli.commands import diff as diff_module
from rocketride.cli.commands.diff import run_diff

# `rocketride.cli.main` must be imported as a module: the `rocketride.cli`
# package re-exports the `main()` function under the same name, which would
# shadow the module on attribute-style imports.
cli_main = importlib.import_module('rocketride.cli.main')


# =========================================================================
# Helpers / fixtures
# =========================================================================


def _diff_args(
    paths=None,
    *,
    git=None,
    include_layout=False,
    json=False,  # noqa: A002 - mirrors the argparse dest name exactly
    markdown=False,
    exit_zero=False,
):
    """Build a parsed-args namespace shaped like the diff subparser's output."""
    return SimpleNamespace(
        paths=list(paths or []),
        git=git,
        include_layout=include_layout,
        json=json,
        markdown=markdown,
        exit_zero=exit_zero,
    )


def _write_pipe(tmp_path, name, obj):
    """Write ``obj`` as JSON to ``name`` under ``tmp_path`` and return the path str."""
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding='utf-8')
    return str(path)


def _old_pipe():
    """A small but complete pipeline: webhook -> chat, with layout and version."""
    return {
        'version': 1,
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
        'components': [
            {
                'id': 'a',
                'provider': 'webhook',
                'config': {'mode': 'Source'},
                'ui': {'position': {'x': 0, 'y': 0}},
            },
            {
                'id': 'b',
                'provider': 'chat',
                'config': {'default': {'strlen': 512}},
                'input': [{'lane': 'text', 'from': 'a'}],
                'ui': {'position': {'x': 10, 'y': 10}},
            },
        ],
    }


def _new_pipe():
    """``_old_pipe`` with a semantic delta: node 'c' added, edge b->c, b.strlen changed."""
    pipe = _old_pipe()
    pipe['components'][1]['config']['default']['strlen'] = 1024
    pipe['components'].append(
        {
            'id': 'c',
            'provider': 'qdrant',
            'config': {},
            'input': [{'lane': 'vec', 'from': 'b'}],
            'ui': {'position': {'x': 20, 'y': 20}},
        }
    )
    return pipe


def _layout_only_new_pipe():
    """``_old_pipe`` with *only* canvas movement: node 'a' relocated, nothing else."""
    pipe = _old_pipe()
    pipe['components'][0]['ui']['position'] = {'x': 400, 'y': 250}
    return pipe


def _viewport_only_new_pipe():
    """``_old_pipe`` with *only* a top-level viewport pan/zoom, no node touched."""
    pipe = _old_pipe()
    pipe['viewport'] = {'x': 120, 'y': 40, 'zoom': 2}
    return pipe


async def _run(args):
    """Execute the diff command body, returning its integer exit code."""
    return await run_diff(args)


# =========================================================================
# Two-file mode
# =========================================================================


@pytest.mark.asyncio
async def test_two_file_changes_exit_1(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _new_pipe())

    code = await _run(_diff_args([old, new]))

    out = capsys.readouterr().out
    assert code == 1
    assert 'Nodes' in out
    assert '+ c (qdrant)' in out
    assert '+ b --vec--> c' in out
    assert 'config.default.strlen' in out


@pytest.mark.asyncio
async def test_identical_files_exit_0(tmp_path, capsys):
    same = _write_pipe(tmp_path, 'same.pipe', _old_pipe())

    code = await _run(_diff_args([same, same]))

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == 'No semantic changes.'
    assert captured.err == ''


# =========================================================================
# --git mode (resolver mocked)
# =========================================================================


@pytest.mark.asyncio
async def test_git_mode_diffs_against_ref(tmp_path, capsys, monkeypatch):
    new = _write_pipe(tmp_path, 'pipeline.pipe', _new_pipe())
    # Resolver returns the *old* pipe as it existed at the ref.
    monkeypatch.setattr(diff_module, 'resolve_git_ref', lambda ref, path: _old_pipe())

    code = await _run(_diff_args([new], git='HEAD'))

    out = capsys.readouterr().out
    assert code == 1
    assert '+ c (qdrant)' in out


@pytest.mark.asyncio
async def test_git_mode_absent_file_is_all_added(tmp_path, capsys, monkeypatch):
    new = _write_pipe(tmp_path, 'pipeline.pipe', _new_pipe())
    # None => file did not exist at the ref; everything is newly added.
    monkeypatch.setattr(diff_module, 'resolve_git_ref', lambda ref, path: None)

    code = await _run(_diff_args([new], git='HEAD', json=True))

    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    added_ids = {n['id'] for n in doc['nodes']['added']}
    assert added_ids == {'a', 'b', 'c'}
    assert doc['nodes']['removed'] == []


@pytest.mark.asyncio
async def test_git_mode_requires_exactly_one_file(tmp_path, capsys):
    a = _write_pipe(tmp_path, 'a.pipe', _old_pipe())
    b = _write_pipe(tmp_path, 'b.pipe', _new_pipe())

    code = await _run(_diff_args([a, b], git='HEAD'))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert '--git requires exactly one FILE' in captured.err


@pytest.mark.asyncio
async def test_git_resolver_error_exit_2(tmp_path, capsys, monkeypatch):
    new = _write_pipe(tmp_path, 'pipeline.pipe', _new_pipe())

    def _boom(ref, path):
        raise diff_module.PipeDiffError('git show HEAD:pipeline.pipe failed: bad ref')

    monkeypatch.setattr(diff_module, 'resolve_git_ref', _boom)

    code = await _run(_diff_args([new], git='HEAD'))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err
    assert 'bad ref' in captured.err


# =========================================================================
# Error / usage handling (exit 2)
# =========================================================================


@pytest.mark.asyncio
async def test_missing_file_exit_2(tmp_path, capsys):
    existing = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    missing = str(tmp_path / 'does_not_exist.pipe')

    code = await _run(_diff_args([existing, missing]))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err


@pytest.mark.asyncio
async def test_invalid_json_exit_2(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    bad = tmp_path / 'bad.pipe'
    bad.write_text('{ this is not json', encoding='utf-8')

    code = await _run(_diff_args([old, str(bad)]))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err


@pytest.mark.asyncio
async def test_non_pipe_object_exit_2(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    # Valid JSON object, but no 'components' list -> not a pipeline.
    notpipe = _write_pipe(tmp_path, 'notpipe.pipe', {'hello': 'world'})

    code = await _run(_diff_args([old, notpipe]))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err


@pytest.mark.asyncio
async def test_wrong_positional_count_exit_2(tmp_path, capsys):
    only = _write_pipe(tmp_path, 'only.pipe', _old_pipe())

    code = await _run(_diff_args([only]))  # one file, no --git

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'two files are required' in captured.err


@pytest.mark.asyncio
async def test_no_files_exit_2(capsys):
    code = await _run(_diff_args([]))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'two files are required' in captured.err


# =========================================================================
# Output-format flags
# =========================================================================


@pytest.mark.asyncio
async def test_json_output_is_pure_and_parseable(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _new_pipe())

    code = await _run(_diff_args([old, new], json=True))

    captured = capsys.readouterr()
    assert code == 1
    # stdout must be exactly one JSON document, nothing else.
    doc = json.loads(captured.out)
    assert set(doc.keys()) == {'nodes', 'edges', 'viewport', 'summary'}
    assert doc['summary']['has_semantic_changes'] is True
    # Without --include-layout the viewport is never enumerated.
    assert doc['viewport'] == []
    assert doc['summary']['viewport_changes'] == 0
    assert captured.err == ''


@pytest.mark.asyncio
async def test_markdown_output(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _new_pipe())

    code = await _run(_diff_args([old, new], markdown=True))

    out = capsys.readouterr().out
    assert code == 1
    assert '**Pipeline diff:**' in out
    assert '**Nodes**' in out
    assert '| Node | Field | Change |' in out


# =========================================================================
# --include-layout
# =========================================================================


@pytest.mark.asyncio
async def test_layout_only_hidden_by_default_exit_0(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _layout_only_new_pipe())

    code = await _run(_diff_args([old, new]))

    out = capsys.readouterr().out
    # Pure canvas movement is non-semantic: exit 0, coarse layout hint, no ui.* lines.
    assert code == 0
    assert 'Layout' in out
    assert 'ui.position' not in out


@pytest.mark.asyncio
async def test_include_layout_surfaces_ui_fields_exit_1(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _layout_only_new_pipe())

    code = await _run(_diff_args([old, new], include_layout=True))

    out = capsys.readouterr().out
    # Opting layout in enumerates ui.* field changes and makes them count.
    assert code == 1
    assert 'ui.position' in out


@pytest.mark.asyncio
async def test_viewport_only_hidden_by_default_exit_0(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _viewport_only_new_pipe())

    code = await _run(_diff_args([old, new]))

    out = capsys.readouterr().out
    assert code == 0
    assert 'Layout' in out
    assert 'viewport.' not in out


@pytest.mark.asyncio
async def test_include_layout_surfaces_viewport_fields_exit_1(tmp_path, capsys):
    # --help and the docs claim --include-layout enumerates the top-level
    # viewport; before this it silently reported nothing and exited 0.
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _viewport_only_new_pipe())

    code = await _run(_diff_args([old, new], include_layout=True, json=True))

    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    paths = [fc['path'] for fc in doc['viewport']]
    assert paths == ['viewport.x', 'viewport.y', 'viewport.zoom']
    assert doc['summary']['viewport_changes'] == 3
    assert doc['summary']['has_semantic_changes'] is True


# =========================================================================
# --exit-zero
# =========================================================================


@pytest.mark.asyncio
async def test_exit_zero_forces_success_on_changes(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _new_pipe())

    code = await _run(_diff_args([old, new], exit_zero=True))

    out = capsys.readouterr().out
    # Changes are still reported, but the exit code is forced to 0 for non-gating use.
    assert code == 0
    assert '+ c (qdrant)' in out


@pytest.mark.asyncio
async def test_exit_zero_does_not_mask_errors(tmp_path, capsys):
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    missing = str(tmp_path / 'nope.pipe')

    code = await _run(_diff_args([old, missing], exit_zero=True))

    captured = capsys.readouterr()
    # --exit-zero only forces 0 on a *successful* run; a load error is still exit 2.
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err


def _nested_pipe_json(depth, leaf=0):
    """Construct real nested JSON without depending on the encoder's limit."""
    return '{"components":[{"id":"n","provider":"p","config":{"deep":' + '[' * depth + str(leaf) + ']' * depth + '}}]}'


def _cli_subprocess(tmp_path, arguments):
    """Run the actual CLI entry point using the package selected by this suite."""
    env = {key: value for key, value in os.environ.items() if not key.startswith('ROCKETRIDE_')}
    # pytest's in-process sys.path is not inherited by subprocesses. Pin the
    # child's import root to this suite's actual package, including wheel runs.
    env['PYTHONPATH'] = str(Path(diff_module.__file__).resolve().parents[3])
    return subprocess.run(
        [
            sys.executable,
            '-c',
            'import sys; from rocketride.cli.main import main; sys.setrecursionlimit(1000); main()',
            'diff',
            *arguments,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _assert_nested_cli_result(result, *, exit_zero, path, kind, old_leaf, new_leaf, depth=0, require_error=False):
    """Require a clean resource error or an accurate, strictly valid JSON report."""
    assert 'Traceback' not in result.stderr
    if result.returncode == 2:
        assert result.stdout == ''
        assert 'Error:' in result.stderr
        assert 'nest' in result.stderr.lower()
        return
    assert not require_error
    assert result.returncode == (0 if exit_zero else 1)
    assert result.stderr == ''

    def reject_constant(token):
        raise ValueError(f'Non-JSON constant {token}')

    # The child has a controlled 1000-frame budget. The parent may have deeper
    # pytest frames and must still be able to inspect a valid supported result.
    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(max(previous_limit, 10000))
        doc = json.loads(result.stdout, parse_constant=reject_constant)
    finally:
        sys.setrecursionlimit(previous_limit)
    assert doc['summary']['has_semantic_changes'] is True
    assert doc['summary']['config_changes'] == 1
    assert doc['summary']['nodes_changed'] == 1
    assert doc['nodes']['added'] == []
    assert doc['nodes']['removed'] == []
    assert doc['edges'] == {'added': [], 'removed': []}
    assert len(doc['nodes']['changed']) == 1
    node = doc['nodes']['changed'][0]
    assert node['id'] == 'n'
    assert node['provider_change'] is None
    assert len(node['config_changes']) == 1
    field = node['config_changes'][0]
    assert field['path'] == path
    assert field['kind'] == kind
    for key, expected in [('old', old_leaf), ('new', new_leaf)]:
        value = field[key]
        if expected is not None:
            for _ in range(depth):
                assert isinstance(value, list) and len(value) == 1
                value = value[0]
        assert type(value) is type(expected)
        assert value == expected


@pytest.mark.parametrize('depth', [981, 2000])
@pytest.mark.parametrize('side', ['old', 'new'])
@pytest.mark.parametrize('exit_zero', [False, True])
def test_excessive_nesting_cli_errors(tmp_path, depth, side, exit_zero):
    # Under the pinned child resource budget, 2000 exceeds JSON loading limits.
    # Historical depth 981 may be supported by another interpreter; a correct
    # report is allowed, while a traceback masquerading as exit 1 is not.
    ordinary = tmp_path / 'ordinary.pipe'
    ordinary.write_text('{"components":[{"id":"n","provider":"p","config":{}}]}', encoding='utf-8')
    nested = tmp_path / 'nested.pipe'
    nested.write_text(_nested_pipe_json(depth), encoding='utf-8')
    paths = [str(nested), str(ordinary)] if side == 'old' else [str(ordinary), str(nested)]
    result = _cli_subprocess(tmp_path, [*paths, '--json', *(['--exit-zero'] if exit_zero else [])])

    _assert_nested_cli_result(
        result,
        exit_zero=exit_zero,
        path='config.deep',
        kind='removed' if side == 'old' else 'added',
        old_leaf=0 if side == 'old' else None,
        new_leaf=0 if side == 'new' else None,
        depth=depth,
        require_error=depth == 2000,
    )


@pytest.mark.parametrize('exit_zero', [False, True])
def test_excessive_comparison_nesting_cli_errors(tmp_path, exit_zero):
    # Both values decode within the JSON limit, but their recursive comparison
    # requires more frames than loading a single value or reporting an add.
    old = tmp_path / 'old.pipe'
    new = tmp_path / 'new.pipe'
    old.write_text(_nested_pipe_json(600, 0), encoding='utf-8')
    new.write_text(_nested_pipe_json(600, 1), encoding='utf-8')

    result = _cli_subprocess(tmp_path, [str(old), str(new), '--json', *(['--exit-zero'] if exit_zero else [])])

    _assert_nested_cli_result(
        result,
        exit_zero=exit_zero,
        path='config.deep' + '[0]' * 600,
        kind='changed',
        old_leaf=0,
        new_leaf=1,
    )


@pytest.mark.parametrize('exit_zero', [False, True])
def test_excessive_historical_nesting_cli_errors(tmp_path, exit_zero):
    git = shutil.which('git')
    if git is None:
        pytest.skip('git is unavailable')
    path = tmp_path / 'pipeline.pipe'
    path.write_text(_nested_pipe_json(981), encoding='utf-8')
    for arguments in [
        ['init'],
        ['add', 'pipeline.pipe'],
        ['-c', 'user.name=Local QA', '-c', 'user.email=qa@example.invalid', 'commit', '-m', 'nested fixture'],
    ]:
        subprocess.run([git, *arguments], cwd=tmp_path, check=True, capture_output=True, timeout=20)
    path.write_text('{"components":[{"id":"n","provider":"p","config":{}}]}', encoding='utf-8')

    result = _cli_subprocess(tmp_path, ['--git', 'HEAD', str(path), '--json', *(['--exit-zero'] if exit_zero else [])])

    _assert_nested_cli_result(
        result,
        exit_zero=exit_zero,
        path='config.deep',
        kind='removed',
        old_leaf=0,
        new_leaf=None,
        depth=981,
    )


@pytest.mark.asyncio
async def test_json_renderer_rejects_nonfinite_output(tmp_path, capsys, monkeypatch):
    # Defense in depth: even an unexpected reporter value must never produce an
    # Infinity token or leak json.dumps' ValueError as an exit-1 traceback.
    path = _write_pipe(tmp_path, 'ordinary.pipe', _old_pipe())
    monkeypatch.setattr(diff_module, 'render_json', lambda diff: {'unexpected': float('inf')})

    code = await _run(_diff_args([path, path], json=True, exit_zero=True))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'Error:' in captured.err
    assert 'JSON compliant' in captured.err


# =========================================================================
# argparse registration (parser-level, no execution)
# =========================================================================


def test_parser_registers_diff_subcommand():
    parser = cli_main.setup_parser()
    ns = parser.parse_args(['diff', 'old.pipe', 'new.pipe'])
    assert ns.command == 'diff'
    assert ns.paths == ['old.pipe', 'new.pipe']
    assert ns.git is None
    assert ns.include_layout is False
    assert ns.json is False
    assert ns.markdown is False
    assert ns.exit_zero is False


def test_parser_diff_takes_no_connection_args():
    parser = cli_main.setup_parser()
    ns = parser.parse_args(['diff', 'old.pipe', 'new.pipe'])
    # This command never touches the engine, so the shared connection args that
    # every other subcommand carries must be absent from its namespace.
    assert not hasattr(ns, 'apikey')
    assert not hasattr(ns, 'uri')
    assert not hasattr(ns, 'token')


def test_parser_json_and_markdown_are_mutually_exclusive():
    parser = cli_main.setup_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(['diff', '--json', '--markdown', 'old.pipe', 'new.pipe'])


def test_diff_is_registered_exactly_once_alongside_validate():
    # The command table must carry both the upstream 'validate' verb and this
    # PR's 'diff' verb, each registered exactly once.
    parser = cli_main.setup_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    names = [choice.dest for choice in subparsers._choices_actions]
    assert names.count('diff') == 1
    assert names.count('validate') == 1


@pytest.mark.asyncio
async def test_dispatch_routes_diff_to_run_diff(tmp_path, capsys):
    # End-to-end through the real parser and dispatcher, not just the body.
    old = _write_pipe(tmp_path, 'old.pipe', _old_pipe())
    new = _write_pipe(tmp_path, 'new.pipe', _new_pipe())

    parser = cli_main.setup_parser()
    ns = parser.parse_args(['diff', old, new])
    code = await cli_main._dispatch(ns)

    out = capsys.readouterr().out
    assert code == 1
    assert '+ c (qdrant)' in out


if __name__ == '__main__':
    import sys

    sys.exit(pytest.main([__file__, '-v']))
