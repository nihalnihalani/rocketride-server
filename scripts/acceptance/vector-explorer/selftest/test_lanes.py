# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Self-tests of lanes.json: which lane owns which file in the Vector Explorer enrichment wave.

``scripts/acceptance/vector-explorer/lanes.json`` lists, per lane, the paths it alone
may change after the day-0 commit (``owns``; a trailing ``/**`` covers a folder) and
the owned paths that did not exist on that commit (``new``); the paths the day-0
commit added or changed (``day0``); and every file the enrichment backlog names
(``backlog``). These tests hold the file to its rules:

* every owned path exists, or is marked new;
* no path has two owners (a folder glob of one lane never covers another lane's path);
* every backlog path and every day-0 path has exactly one owner;
* the checker itself reports each kind of mistake (it is run on broken copies).

At each gate the per-lane diff is checked from the command line, which lists every
changed path outside the lane's list and exits 1 when there is one:

    python3 scripts/acceptance/vector-explorer/selftest/test_lanes.py diff <lane> <day-0 commit> <lane tip>
    python3 scripts/acceptance/vector-explorer/selftest/test_lanes.py diff-all   # every lane branch since day0_commit
    python3 scripts/acceptance/vector-explorer/selftest/test_lanes.py check
    python3 scripts/acceptance/vector-explorer/selftest/test_lanes.py day0       # new/owned paths against day0_commit, merge_order

``day0_commit`` is the commit every lane branches from; ``merge_order`` the order
the lanes merge into the integration branch (the acceptance lane last, because it
regenerates the live wire fixtures over every other lane's code).

Run the tests: python3 -m unittest discover -s scripts/acceptance/vector-explorer/selftest -p test_lanes.py -v
"""

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
LANES_JSON = HERE.parent / 'lanes.json'
REPO = HERE.parents[3]

#: The lanes of the wave, in order.
LANE_IDS = ['E0', 'E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E7', 'E8', 'E9', 'E10']


def load(path: Path = LANES_JSON) -> Dict[str, Any]:
    """Read lanes.json."""
    return json.loads(path.read_text(encoding='utf-8'))


def covers(owned: str, path: str) -> bool:
    """Whether an owned entry (a path, or a folder ending in ``/**``) covers a repository path."""
    if owned.endswith('/**'):
        return path.startswith(owned[:-2])
    return path == owned


def owners(doc: Dict[str, Any], path: str) -> List[str]:
    """The lanes whose list covers ``path``."""
    return [lane['lane'] for lane in doc['lanes'] if any(covers(owned, path) for owned in lane['owns'])]


def present(path: str, root: Path = REPO) -> bool:
    """Whether a listed path exists under ``root`` (a ``/**`` entry: its folder)."""
    target = root / (path[:-3] if path.endswith('/**') else path)
    return target.is_dir() if path.endswith('/**') else target.exists()


def problems(doc: Dict[str, Any], exists: Callable[[str], bool] = present) -> List[str]:
    """Every rule of lanes.json the document breaks, as sentences (none: it is sound)."""
    out: List[str] = []
    ids = [lane.get('lane') for lane in doc.get('lanes', [])]
    if ids != LANE_IDS:
        out.append(f'the lanes are {ids}, expected {LANE_IDS}')
    branches = [lane.get('branch') for lane in doc.get('lanes', [])]
    if len(set(branches)) != len(branches) or not all(isinstance(b, str) and b.startswith('vx/') for b in branches):
        out.append(f'every lane needs its own vx/ branch: {branches}')
    for lane in doc.get('lanes', []):
        name = lane.get('lane')
        owns, new = lane.get('owns', []), lane.get('new', [])
        if len(set(owns)) != len(owns):
            out.append(f'{name} lists a path twice')
        for path in new:
            if path not in owns:
                out.append(f'{name} marks {path} new but does not own it')
        for path in owns:
            if path not in new and not exists(path):
                out.append(f'{name} owns {path}, which does not exist and is not marked new')
    # Two owners: an exact repeat, or a folder of one lane covering another lane's path or folder.
    entries = [(lane['lane'], owned) for lane in doc.get('lanes', []) for owned in lane.get('owns', [])]
    for i, (lane_a, a) in enumerate(entries):
        for lane_b, b in entries[i + 1 :]:
            if lane_a != lane_b and (
                covers(a, b.rstrip('*').rstrip('/')) or covers(b, a.rstrip('*').rstrip('/')) or a == b
            ):
                out.append(f'{a} ({lane_a}) and {b} ({lane_b}) overlap')
    for key in ('backlog', 'day0'):
        for path in doc.get(key, []):
            found = owners(doc, path)
            if len(found) != 1:
                out.append(f'{key} path {path} has {len(found)} owners {found}')
    for path in doc.get('day0', []):
        if not exists(path):
            out.append(f'day-0 path {path} does not exist')
    return out


def outside(doc: Dict[str, Any], lane: str, paths: Iterable[str]) -> List[str]:
    """The changed paths a lane's list does not cover."""
    entry = next((item for item in doc['lanes'] if item['lane'] == lane), None)
    if entry is None:
        raise ValueError(f'no lane {lane} in lanes.json')
    return sorted(path for path in set(paths) if not any(covers(owned, path) for owned in entry['owns']))


def at_commit(commit: str, path: str, root: Path = REPO) -> bool:
    """Whether ``path`` (a file, or for a ``/**`` entry its folder) exists on ``commit``."""
    target = path[:-3] if path.endswith('/**') else path
    result = subprocess.run(
        ['git', 'cat-file', '-e', f'{commit}:{target}'], cwd=root, capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def day0_problems(doc: Dict[str, Any], exists: Callable[[str, str], bool] = at_commit) -> List[str]:
    """Owned paths the day-0 commit contradicts: one marked new that it already has, one not new that it lacks."""
    commit = doc.get('day0_commit', '')
    out: List[str] = []
    for lane in doc.get('lanes', []):
        for path in lane.get('owns', []):
            here = exists(commit, path)
            if path in lane.get('new', []) and here:
                out.append(f'{lane["lane"]} marked {path} new but exists on the day-0 commit {commit}')
            elif path not in lane.get('new', []) and not here:
                out.append(f'{lane["lane"]} owns {path}, which is not on the day-0 commit {commit} and not marked new')
    return out


def order_problems(doc: Dict[str, Any]) -> List[str]:
    """What is wrong with ``merge_order``: every lane but the lead's once, the acceptance lane last."""
    order = doc.get('merge_order', [])
    out: List[str] = []
    if len(set(order)) != len(order):
        out.append(f'merge_order names a lane twice: {order}')
    if set(order) != set(LANE_IDS[1:]):
        out.append(f'merge_order must name {LANE_IDS[1:]} once each, not {order}')
    if order and order[-1] != 'E10':
        out.append('the acceptance lane (E10) merges last: it regenerates the live fixtures over every other lane')
    return out


def branch_present(branch: str, root: Path = REPO) -> bool:
    """Whether a local branch exists."""
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}'], cwd=root, capture_output=True, check=False
    )
    return result.returncode == 0


def diff_all(
    doc: Dict[str, Any],
    changed_paths: Callable[..., List[str]] = None,
    branch_exists: Callable[[str], bool] = branch_present,
) -> Dict[str, Optional[List[str]]]:
    """Every lane's paths outside its list, from the day-0 commit to its branch (None: no such branch)."""
    changed_paths = changed_paths or changed
    report: Dict[str, Optional[List[str]]] = {}
    for lane in doc['lanes'][1:]:
        branch = lane['branch']
        report[lane['lane']] = (
            outside(doc, lane['lane'], changed_paths(doc['day0_commit'], branch)) if branch_exists(branch) else None
        )
    return report


def changed(base: str, tip: str, root: Path = REPO) -> List[str]:
    """The paths changed between two commits (a rename counts as both of its paths)."""
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--no-renames', f'{base}..{tip}'],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


class LanesFileTests(unittest.TestCase):
    """lanes.json as committed."""

    def setUp(self):
        self.doc = load()

    def test_the_file_has_every_lane_with_its_branch(self):
        self.assertEqual([lane['lane'] for lane in self.doc['lanes']], LANE_IDS)
        self.assertEqual(self.doc['lanes'][0]['branch'], 'vx/integration')
        for lane in self.doc['lanes']:
            self.assertTrue(lane['title'] and lane['owns'], lane['lane'])

    def test_the_file_breaks_none_of_its_rules(self):
        self.assertEqual(problems(self.doc), [])

    def test_every_owned_path_exists_or_is_marked_new(self):
        for lane in self.doc['lanes']:
            for path in lane['owns']:
                if path not in lane['new']:
                    self.assertTrue(present(path), f'{lane["lane"]}: {path}')

    def test_the_backlog_and_the_day0_commit_are_each_owned_once(self):
        self.assertGreaterEqual(len(self.doc['backlog']), 100)
        self.assertGreaterEqual(len(self.doc['day0']), 50)
        for key in ('backlog', 'day0'):
            for path in self.doc[key]:
                self.assertEqual(len(owners(self.doc, path)), 1, f'{key}: {path}')

    def test_this_file_and_lanes_json_are_owned_by_the_acceptance_lane(self):
        for path in (
            'scripts/acceptance/vector-explorer/lanes.json',
            'scripts/acceptance/vector-explorer/selftest/test_lanes.py',
        ):
            self.assertEqual(owners(self.doc, path), ['E10'], path)
            self.assertIn(path, self.doc['day0'])


class Day0AndOrderTests(unittest.TestCase):
    """The day-0 commit lanes.json names, and the order the lanes merge in."""

    def setUp(self):
        self.doc = load()

    def test_the_file_names_the_day0_commit_and_the_merge_order(self):
        self.assertRegex(self.doc.get('day0_commit', ''), r'^[0-9a-f]{9,40}$')
        self.assertEqual(sorted(self.doc['merge_order']), sorted(LANE_IDS[1:]))
        self.assertEqual(order_problems(self.doc), [])

    def test_new_paths_are_new_and_owned_paths_exist_on_the_day0_commit(self):
        commit = self.doc['day0_commit']
        if not at_commit(commit, 'scripts/acceptance/vector-explorer/lanes.json'):
            self.skipTest(f'the day-0 commit {commit} is not in this clone')
        self.assertEqual(day0_problems(self.doc), [])

    def test_the_day0_checker_reports_each_kind_of_mistake(self):
        doc = copy.deepcopy(self.doc)
        lane = next(item for item in doc['lanes'] if item['lane'] == 'E10')
        lane['new'].append('scripts/acceptance/vector-explorer/lanes.json')
        lane['owns'].append('scripts/acceptance/vector-explorer/not_on_day0.py')
        found = day0_problems(doc, exists=lambda commit, path: path == 'scripts/acceptance/vector-explorer/lanes.json')
        self.assertTrue(any('lanes.json new but exists on the day-0 commit' in line for line in found), found)
        self.assertTrue(any('not_on_day0.py' in line and 'not on the day-0 commit' in line for line in found), found)

    def test_the_order_checker_reports_each_kind_of_mistake(self):
        for name, breaks in {
            'a lane missing': lambda d: d['merge_order'].remove('E4'),
            'a lane twice': lambda d: d['merge_order'].append('E1'),
            'the lead lane': lambda d: d['merge_order'].insert(0, 'E0'),
            'the acceptance lane not last': lambda d: d['merge_order'].insert(0, d['merge_order'].pop()),
            'an unknown lane': lambda d: d['merge_order'].append('E11'),
        }.items():
            doc = copy.deepcopy(self.doc)
            breaks(doc)
            self.assertNotEqual(order_problems(doc), [], name)

    def test_every_lane_branch_can_be_checked_at_once(self):
        doc = self.doc
        calls = []

        def fake_changed(base, tip, root=REPO):
            calls.append((base, tip))
            return {
                'vx/acceptance-2': [
                    'scripts/acceptance/vector-explorer/lanes.json',
                    'apps/vector-ui/src/views/MapView.tsx',
                ]
            }.get(tip, [])

        report = diff_all(doc, changed_paths=fake_changed, branch_exists=lambda b: b != 'vx/app-ingest-2')
        self.assertEqual(report['E10'], ['apps/vector-ui/src/views/MapView.tsx'])
        self.assertEqual(report['E1'], [])
        self.assertIsNone(report['E9'], 'a lane whose branch does not exist is reported as unchecked')
        self.assertNotIn('E0', report)
        self.assertTrue(all(base == doc['day0_commit'] for base, _ in calls))


class CheckerTests(unittest.TestCase):
    """The checker on small documents, sound and broken, so a pass is never vacuous."""

    def sound(self) -> Dict[str, Any]:
        lanes = [
            {'lane': lane, 'branch': f'vx/{lane.lower()}', 'title': lane, 'owns': [f'src/{lane}.ts'], 'new': []}
            for lane in LANE_IDS
        ]
        lanes[1]['owns'].append('nodes/mocks/client/**')
        lanes[2]['owns'].append('src/new_module.ts')
        lanes[2]['new'].append('src/new_module.ts')
        return {'lanes': lanes, 'backlog': ['src/E3.ts', 'nodes/mocks/client/models.py'], 'day0': ['src/E0.ts']}

    @staticmethod
    def exists(path: str) -> bool:
        return path != 'src/new_module.ts' and path != 'src/missing.ts'

    def test_a_sound_document_has_no_problem(self):
        self.assertEqual(problems(self.sound(), self.exists), [])

    def test_each_kind_of_mistake_is_reported(self):
        cases = {
            'two owners': lambda d: d['lanes'][5]['owns'].append('src/E4.ts'),
            'a folder covering another lane': lambda d: d['lanes'][7]['owns'].append('nodes/mocks/client/models.py'),
            'a path that does not exist': lambda d: d['lanes'][3]['owns'].append('src/missing.ts'),
            'new but not owned': lambda d: d['lanes'][4]['new'].append('src/E5.ts'),
            'a backlog path nobody owns': lambda d: d['backlog'].append('src/orphan.ts'),
            'a day-0 path nobody owns': lambda d: d['day0'].append('src/orphan.ts'),
            'a day-0 path that does not exist': lambda d: (
                d['lanes'][0]['owns'].append('src/missing.ts'),
                d['lanes'][0]['new'].append('src/missing.ts'),
                d['day0'].append('src/missing.ts'),
            ),
            'a lane missing': lambda d: d['lanes'].pop(),
            'a shared branch': lambda d: d['lanes'][2].update(branch='vx/e1'),
            'a path listed twice': lambda d: d['lanes'][6]['owns'].append('src/E6.ts'),
        }
        for name, breaks in cases.items():
            doc = copy.deepcopy(self.sound())
            breaks(doc)
            self.assertNotEqual(problems(doc, self.exists), [], name)

    def test_outside_lists_exactly_what_a_lane_may_not_change(self):
        doc = self.sound()
        changed_paths = [
            'src/E1.ts',
            'nodes/mocks/client/models.py',
            'nodes/mocks/client/sub/x.py',
            'src/E2.ts',
            'nodes/mocks/clientele.py',
        ]
        self.assertEqual(outside(doc, 'E1', changed_paths), ['nodes/mocks/clientele.py', 'src/E2.ts'])
        self.assertEqual(outside(doc, 'E1', []), [])
        with self.assertRaises(ValueError):
            outside(doc, 'E11', changed_paths)

    def test_a_folder_glob_covers_its_folder_only(self):
        self.assertTrue(covers('a/b/**', 'a/b/c'))
        self.assertTrue(covers('a/b/**', 'a/b/c/d.py'))
        self.assertFalse(covers('a/b/**', 'a/bc/d.py'))
        self.assertFalse(covers('a/b.py', 'a/b.pyc'))


def main(argv: List[str]) -> int:
    """``diff <lane> <base> <tip>``, ``diff-all``, ``check`` or ``day0``; anything else runs the tests."""
    if argv == ['diff-all']:
        report = diff_all(load())
        for lane, stray in report.items():
            if stray is None:
                print(f'{lane}: no branch')
            for path in stray or []:
                print(f'{lane} changed {path}, which is not in its list')
        strays = sum(len(stray or []) for stray in report.values())
        print(f'{strays} paths outside their lane lists since {load()["day0_commit"]}')
        return 1 if strays else 0
    if argv == ['day0']:
        found = day0_problems(load()) + order_problems(load())
        for line in found:
            print(line)
        print(f'lanes.json against its day-0 commit: {len(found)} problems')
        return 1 if found else 0
    if len(argv) == 4 and argv[0] == 'diff':
        lane, base, tip = argv[1:]
        stray = outside(load(), lane, changed(base, tip))
        for path in stray:
            print(f'{lane} changed {path}, which is not in its list')
        print(f'{lane}: {len(stray)} paths outside its list between {base} and {tip}')
        return 1 if stray else 0
    if argv == ['check']:
        found = problems(load())
        for line in found:
            print(line)
        print(f'lanes.json: {len(found)} problems')
        return 1 if found else 0
    return 0 if unittest.main(argv=[sys.argv[0], *argv], exit=False).result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
