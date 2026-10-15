# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
# =============================================================================

"""preprocessor_langchain hands the configured chunk length to its LangChain splitter."""

import pytest

langchain_text_splitters = pytest.importorskip('langchain_text_splitters')


def test_the_splitter_receives_chunk_size_overlap_and_length_function():
    from nodes.preprocessor_langchain.langchain import PreProcessor

    kept = PreProcessor._filter_kwargs_for(
        None,
        langchain_text_splitters.RecursiveCharacterTextSplitter,
        {'chunk_size': 1000, 'chunk_overlap': 0, 'length_function': len, 'separators': None, 'bogus': 1},
    )
    assert kept == {'chunk_size': 1000, 'chunk_overlap': 0, 'length_function': len, 'separators': None}
    splitter = langchain_text_splitters.RecursiveCharacterTextSplitter(**kept)
    assert max(len(c) for c in splitter.split_text('word ' * 2000)) <= 1000
