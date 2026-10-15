# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""preprocessor_langchain hands the configured chunk length to its LangChain splitter."""

import contextlib
import importlib
import importlib.util
import sys
import types

import pytest

# Top-level packages whose sys.modules entries are set aside and restored around the import.
_LANGCHAIN_ROOTS = ('langchain', 'langchain_core', 'langchain_text_splitters')


def _is_stand_in(mod) -> bool:
    """True for a hand-built module object (types.ModuleType or a mock), not one loaded from disk.

    A real module or package carries a __file__ or a non-empty __path__; a stand-in
    registered by another test module carries neither.
    """
    if mod is None:
        return False
    if getattr(mod, '__file__', None) is not None:
        return False
    return not getattr(mod, '__path__', None)


def _langchain_entries():
    return {name: mod for name, mod in sys.modules.items() if name.split('.', 1)[0] in _LANGCHAIN_ROOTS}


@contextlib.contextmanager
def _real_text_splitters():
    """Import the real langchain_text_splitters past any langchain stand-ins, then restore sys.modules.

    Other node tests register bare module objects named langchain_core,
    langchain_core.messages, langchain, ... in sys.modules while pytest collects
    them, and leave them there for their own tests. Because those objects are not
    packages, importing the real splitter package behind them fails with
    "'langchain_core' is not a package". This sets the stand-ins aside, imports
    the real package, and on exit puts every langchain entry of sys.modules back
    exactly as it found it, so the other tests still see their stand-ins whatever
    order the tests run in.

    Skips only when the package is not installed in this Python; an installed
    package that fails to import is a failure, not a skip.
    """
    saved = _langchain_entries()
    for name, mod in saved.items():
        if _is_stand_in(mod):
            del sys.modules[name]
    try:
        if importlib.util.find_spec('langchain_text_splitters') is None:
            pytest.skip('NOT RUN: langchain_text_splitters is not installed in this Python (run with the engine)')
        yield importlib.import_module('langchain_text_splitters')
    finally:
        for name in list(_langchain_entries()):
            del sys.modules[name]
        sys.modules.update(saved)


@pytest.fixture
def text_splitters():
    """The real langchain_text_splitters package (see _real_text_splitters)."""
    with _real_text_splitters() as module:
        yield module


def test_the_splitter_receives_chunk_size_overlap_and_length_function(text_splitters):
    from nodes.preprocessor_langchain.langchain import PreProcessor

    kept = PreProcessor._filter_kwargs_for(
        None,
        text_splitters.RecursiveCharacterTextSplitter,
        {'chunk_size': 1000, 'chunk_overlap': 0, 'length_function': len, 'separators': None, 'bogus': 1},
    )
    assert kept == {'chunk_size': 1000, 'chunk_overlap': 0, 'length_function': len, 'separators': None}
    splitter = text_splitters.RecursiveCharacterTextSplitter(**kept)
    assert max(len(c) for c in splitter.split_text('word ' * 2000)) <= 1000


def test_the_import_gets_past_a_langchain_core_stand_in_and_puts_it_back(monkeypatch):
    # What a stub-installing test module leaves behind: bare, non-package module objects.
    core = types.ModuleType('langchain_core')
    messages = types.ModuleType('langchain_core.messages')
    core.messages = messages
    monkeypatch.setitem(sys.modules, 'langchain_core', core)
    monkeypatch.setitem(sys.modules, 'langchain_core.messages', messages)
    monkeypatch.delitem(sys.modules, 'langchain_text_splitters', raising=False)

    with _real_text_splitters() as module:
        assert getattr(module, '__file__', None) is not None
        assert getattr(sys.modules['langchain_core'], '__path__', None), 'the real langchain_core is loaded inside'

    assert sys.modules['langchain_core'] is core
    assert sys.modules['langchain_core.messages'] is messages
    assert 'langchain_text_splitters' not in sys.modules
