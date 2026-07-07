# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""Unit tests for local_text_output IInstance (no engine server required)."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

NODES_SRC = str(Path(__file__).resolve().parent.parent.parent / 'src' / 'nodes')
# Force the node source to the FRONT of sys.path: this test directory is itself
# importable as ``local_text_output`` (it has an ``__init__.py``), so unless the
# real node package is searched first the test dir shadows it and breaks
# ``from local_text_output.IInstance import IInstance``. A plain "if not in
# sys.path" guard is insufficient -- another node suite may already have added
# the path *behind* this test dir, letting the test dir win.
while NODES_SRC in sys.path:
    sys.path.remove(NODES_SRC)
sys.path.insert(0, NODES_SRC)

from local_text_output.IInstance import IInstance  # noqa: E402


def _make_instance():
    inst = IInstance()
    iglobal = Mock()
    iglobal.output_path = str(Path(tempfile.gettempdir()) / 'local_text_output_test')
    iglobal.exclude = 'N/A'
    inst.IGlobal = iglobal
    return inst


def test_write_text_before_open_does_not_raise():
    """Regression: writeText used to do None += str when open() had not run."""
    inst = _make_instance()
    inst.writeText('chunk')
    assert inst.target_object_text is None


def test_write_text_after_open_accumulates():
    """open() initializes the buffer; writeText appends in order."""
    inst = _make_instance()
    entry = Mock()
    entry.objectFailed = False
    entry.path = '/data/doc.md'
    inst.open(entry)
    inst.writeText('a')
    inst.writeText('b')
    assert inst.target_object_text == 'ab'


def test_write_text_coerces_none_buffer_when_object_open():
    """If buffer were None while an object is open, += must not crash."""
    inst = _make_instance()
    entry = Mock()
    entry.objectFailed = False
    entry.path = '/data/doc.md'
    inst.open(entry)
    inst.target_object_text = None
    inst.writeText('x')
    assert inst.target_object_text == 'x'
