# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

from typing import Any, Dict, Optional

from ai.common.schema import Question
from ai.common.utils import merge_metadata


def question_text(item: Dict[str, Any]) -> Optional[str]:
    """Return a dataset item's prompt, or None when the row carries none.

    ``DatasetLoader.to_questions`` falls back to ``''`` for a row holding none
    of ``input``/``text``/``question`` - a typo'd key or a renamed CSV column
    is enough. Such a row has nothing to ask, so both emission lanes drop it
    rather than emitting a question with no prompt at all.

    ``0`` and ``False`` are legitimate prompts and are preserved as their
    string form; only ``None`` and ``''`` mean "no text".

    Args:
        item: Dataset item with an optional 'text' key holding the prompt.

    Returns:
        The prompt as a string, or None when the row has no prompt.
    """
    text = item.get('text')
    if text is None or text == '':
        return None
    return str(text)


def skipped_rows_warning(count: int) -> str:
    """Return the shared wording for a text-less-row skip warning.

    Filter mode and source mode skip on the same rule, so they report it with
    the same sentence; only the node-position prefix differs.
    """
    return f'skipped {count} row(s) with no input text'


def question_from_item(item: Dict[str, Any]) -> Optional[Question]:
    """Build a Question from a dataset item.

    Args:
        item: Dataset item with an optional 'text' key holding the prompt and
            an optional 'metadata' dict carrying the reference answer. The
            metadata is attached to the Question but never rendered into the
            prompt, so a downstream LLM never sees the expected answer.

    Returns:
        A Question carrying the item's text and metadata, or None when the
        item carries no prompt text and must therefore be skipped.
    """
    text = question_text(item)
    if text is None:
        return None

    question = Question()
    question.addQuestion(text)

    merge_metadata(question, item.get('metadata', {}))

    return question
