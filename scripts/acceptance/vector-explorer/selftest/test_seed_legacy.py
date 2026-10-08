# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Self-tests for the legacy seed's own logic (no engine, database or network).

They check that its verification cannot pass a collection that is not what the
driver suites expect (one control record, exactly the planted document without
chunk 0, every document present, no meta column), that it only ever drops the
legacy names, and that the control row matches the old driver's columns.

Run: python3 -m unittest discover -s scripts/acceptance/vector-explorer/selftest -v
"""

import importlib.util
import re
import sys
import unittest

from pathlib import Path

ACC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACC))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


seed = _load('vx_seed_legacy', ACC / 'seed_legacy.py')


class OrphanTests(unittest.TestCase):
    def test_a_document_without_chunk_0_is_an_orphan(self):
        rows = [('schema', 0), ('a', 0), ('a', 1), ('b', 1), ('b', 2), ('c', 0)]
        self.assertEqual(seed.orphans(rows), ['b'])

    def test_the_control_record_is_never_an_orphan(self):
        self.assertEqual(seed.orphans([('schema', 3)]), [])


class VerdictTests(unittest.TestCase):
    def ok(self, **overrides):
        args = dict(
            control=1,
            orphan_ids=['x'],
            expected_orphan='x',
            documents=40,
            expected_documents=40,
            meta_column=False,
            long_manual_chunks=159,
            median_chunk_chars=806,
        )
        args.update(overrides)
        return seed.verdict('pgvector', **args)

    def test_the_promised_collection_passes(self):
        self.assertEqual(self.ok(), [])

    def test_each_broken_promise_is_a_problem(self):
        self.assertTrue(self.ok(control=0))
        self.assertTrue(self.ok(control=2))
        self.assertTrue(self.ok(orphan_ids=[]))
        self.assertTrue(self.ok(orphan_ids=['x', 'y']))
        self.assertTrue(self.ok(orphan_ids=['y']))
        self.assertTrue(self.ok(expected_orphan=None, orphan_ids=[]))
        self.assertTrue(self.ok(documents=39))
        self.assertTrue(self.ok(meta_column=True))
        self.assertTrue(self.ok(missing=['a-missing-document']))

    def test_a_collection_chunked_without_the_calibrated_length_fails(self):
        # A seed on an engine whose chunker ignores strlen: about 33 chunks of up to 4,000 characters.
        self.assertTrue(self.ok(long_manual_chunks=33))
        self.assertTrue(self.ok(median_chunk_chars=3409))
        self.assertTrue(self.ok(median_chunk_chars=399))
        self.assertTrue(self.ok(median_chunk_chars=None))
        # The long manual keeps more than 64 chunks: at least 64 rows once chunk 0 is gone.
        self.assertTrue(self.ok(long_manual_chunks=63))
        self.assertEqual(self.ok(long_manual_chunks=64, median_chunk_chars=1200), [])

    def test_the_median_skips_the_control_record(self):
        self.assertEqual(seed.median_length(['', 'abcd', 'ab', 'abcdef']), 4)
        self.assertIsNone(seed.median_length([]))

    def test_object_ids_follow_the_engine(self):
        # Observed on the engine: an upload named '/srv/legacy/ops/memo_q2.txt' is stored with
        # parent 'srv/legacy/ops/memo_q2.txt' and this objectId (derived from the name as sent).
        self.assertEqual(seed.fx.object_id('/srv/legacy/ops/memo_q2.txt'), '9f2bee29-b134-547e-9ba8-2ff9f8dd0f42')


class SafetyTests(unittest.TestCase):
    def test_only_legacy_names_are_dropped(self):
        self.assertEqual(seed._guard('vx_legacy_docs'), 'vx_legacy_docs')
        for name in ('vx_demo_docs', 'rocketride', 'legacy', 'vx_legacy'):
            with self.assertRaises(ValueError):
                seed._guard(name)

    def test_the_control_row_has_the_old_drivers_columns(self):
        ddl_columns = re.findall(r'(\w+) (?:bigserial|text|int|boolean|vector)', seed.LEGACY_DDL)
        self.assertEqual(sorted(c.lower() for c in ddl_columns if c != 'id'), sorted(seed.control_row()))

    def test_the_control_row_is_createCollections(self):
        row = seed.control_row(model='m', dim=3)
        self.assertEqual(row['objectid'], 'schema')
        self.assertIs(row['isdeleted'], True)
        self.assertEqual(row['chunkid'], 0)
        self.assertEqual((row['vectorsize'], row['modelname'], row['content']), (3, 'm', ''))
        self.assertEqual(row['embedding'], '[0,0,0]')
        self.assertEqual(
            [k for k, v in row.items() if v is None],
            ['nodeid', 'parent', 'permissionid', 'istable', 'tableid', 'signature'],
        )

    def test_paths_are_posix_under_the_legacy_prefix(self):
        corpus = seed._corpus()
        names = seed.corpus_names(corpus)
        self.assertEqual(len(names), 40)
        self.assertTrue(all(n.startswith('/srv/legacy/') for n in names))
        self.assertIn(seed.PREFIX + seed.ORPHAN_REL, names)
        kitchen = seed.corpus_names(corpus, seed.RR_PREFIX, seed.RR_FOLDER)
        self.assertTrue(kitchen and all(n.startswith('/srv/legacy-rr/kitchen/') for n in kitchen))


if __name__ == '__main__':
    unittest.main()
