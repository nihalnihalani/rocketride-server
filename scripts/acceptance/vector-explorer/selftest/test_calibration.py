# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================
"""Self-tests for the chunking calibration (G0-6) and the templates it writes.

No engine is needed: the measurement helpers are pure, and the writer is run
against copies of the templates in a temporary directory.

Run: python3 -m unittest discover -s scripts/acceptance/vector-explorer/selftest -v
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest

from pathlib import Path

ACC = Path(__file__).resolve().parent.parent
REPO = ACC.parent.parent.parent
TEMPLATES = REPO / 'apps' / 'vector-ui' / 'templates'
CHUNKING = REPO / 'apps' / 'vector-ui' / 'tests' / 'fixtures' / 'chunking.json'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cal = _load('vx_calibrate_chunking', ACC / 'calibrate_chunking.py')


class SummaryTests(unittest.TestCase):
    def test_summary_counts_and_median(self):
        lengths = {'a.md': [100, 900, 800], 'b.md': [700], 'manuals/long_manual.md': [600] * 70}
        s = cal.summarise(lengths, 'manuals/long_manual.md')
        self.assertEqual(s['documents'], 3)
        self.assertEqual(s['chunks'], 74)
        self.assertEqual(s['median_chars'], 600)
        self.assertEqual(s['single_chunk_documents'], 1)
        self.assertEqual(s['long_document_chunks'], 70)
        self.assertEqual(s['max_chars'], 900)

    def test_target_is_a_median_of_400_to_1200_characters(self):
        self.assertTrue(cal.in_target({'median_chars': 400}))
        self.assertTrue(cal.in_target({'median_chars': 1200}))
        self.assertFalse(cal.in_target({'median_chars': 399}))
        self.assertFalse(cal.in_target({'median_chars': 3409}))
        self.assertFalse(cal.in_target({}))

    def test_identical_results_for_different_lengths_mean_the_setting_is_ignored(self):
        same = {'documents': 40, 'chunks': 81, 'median_chars': 3409}
        self.assertTrue(cal.setting_ignored({'512': dict(same), '1000': dict(same)}))
        self.assertFalse(cal.setting_ignored({'512': dict(same), '1000': {**same, 'chunks': 306}}))
        # One candidate proves nothing either way.
        self.assertFalse(cal.setting_ignored({'1000': dict(same)}))


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.templates = self.tmp / 'templates'
        shutil.copytree(TEMPLATES, self.templates)
        self.chunking = self.tmp / 'chunking.json'
        shutil.copy(CHUNKING, self.chunking)
        self._saved = (cal.TEMPLATES, cal.CHUNKING)
        cal.TEMPLATES, cal.CHUNKING = self.templates, self.chunking

    def tearDown(self):
        cal.TEMPLATES, cal.CHUNKING = self._saved
        shutil.rmtree(self.tmp)

    def test_write_records_the_choice_and_sets_every_template(self):
        summary = {'documents': 40, 'chunks': 306, 'median_chars': 806, 'in_target': True}
        cal.write_choice(1000, summary, {'1000': summary}, '40 documents')
        record = json.loads(self.chunking.read_text(encoding='utf-8'))
        self.assertIs(record['calibrated'], True)
        self.assertEqual(record['measured'], summary)
        self.assertEqual(record['chunk_1']['config']['default']['strlen'], 1000)
        pipes = sorted(self.templates.glob('*.pipe'))
        self.assertEqual(len(pipes), 9)
        for path in pipes:
            pipe = json.loads(path.read_text(encoding='utf-8'))
            (chunker,) = [c for c in pipe['components'] if c['id'] == 'chunk_1']
            self.assertEqual(chunker['config'], record['chunk_1']['config'], path.name)
            self.assertEqual(chunker['provider'], record['chunk_1']['provider'], path.name)
            # The template formatting is kept (2-space JSON, trailing newline).
            self.assertEqual(path.read_text(encoding='utf-8'), json.dumps(pipe, indent=2) + '\n')

    def test_write_keeps_a_recorded_known_issue(self):
        record = json.loads(self.chunking.read_text(encoding='utf-8'))
        record['known_issue'] = 'kept across rewrites'
        self.chunking.write_text(json.dumps(record, indent='\t') + '\n', encoding='utf-8')
        cal.write_choice(1000, {'median_chars': 806}, {}, '40 documents')
        self.assertEqual(json.loads(self.chunking.read_text(encoding='utf-8'))['known_issue'], 'kept across rewrites')


class CommittedTemplatesTests(unittest.TestCase):
    """The committed templates carry the committed calibration (what L7's templates test pins too)."""

    def test_calibrated_and_in_target(self):
        record = json.loads(CHUNKING.read_text(encoding='utf-8'))
        self.assertIs(record['calibrated'], True, 'chunking.json is not calibrated yet')
        self.assertTrue(cal.in_target(record['measured']))
        self.assertGreater(record['measured']['long_document_chunks'], 64)

    def test_every_template_carries_the_calibrated_chunker(self):
        record = json.loads(CHUNKING.read_text(encoding='utf-8'))
        for path in sorted(TEMPLATES.glob('*.pipe')):
            pipe = json.loads(path.read_text(encoding='utf-8'))
            (chunker,) = [c for c in pipe['components'] if c['id'] == 'chunk_1']
            self.assertEqual(chunker['provider'], record['chunk_1']['provider'], path.name)
            self.assertEqual(chunker['config'], record['chunk_1']['config'], path.name)


if __name__ == '__main__':
    unittest.main()
