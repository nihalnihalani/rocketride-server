from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path
from typing import Any, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[6]
_UTILS = _REPO_ROOT / 'packages' / 'ai' / 'src' / 'ai' / 'common' / 'utils'


def _load_attr(module_name: str, path: Path, attr: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return getattr(module, attr)


if 'depends' not in sys.modules:
    sys.modules['depends'] = types.SimpleNamespace(depends=lambda *_args, **_kwargs: None)

if 'rocketlib' not in sys.modules:
    rocketlib = types.ModuleType('rocketlib')
    rocketlib.ToolDescriptor = object
    rocketlib.debug = lambda *_args, **_kwargs: None
    rocketlib.error = lambda *_args, **_kwargs: None
    sys.modules['rocketlib'] = rocketlib

if 'rocketlib.types' not in sys.modules:
    rocketlib_types = types.ModuleType('rocketlib.types')
    rocketlib_types.IInvokeMemory = object
    rocketlib_types.IInvokeOp = object
    rocketlib_types.IInvokeTool = object
    sys.modules['rocketlib.types'] = rocketlib_types

if 'ai.common.config' not in sys.modules:
    sys.modules['ai.common.config'] = types.SimpleNamespace(Config=object)

if 'ai.common.utils' not in sys.modules:
    sys.modules['ai.common.utils'] = types.SimpleNamespace(
        merge_metadata=_load_attr('ai.common.utils.metadata_utils', _UTILS / 'metadata_utils.py', 'merge_metadata'),
        safe_str=_load_attr('ai.common.utils.string_utils', _UTILS / 'string_utils.py', 'safe_str'),
    )

from ai.common.agent import AgentBase
from ai.common.agent._internal.host import AgentContext
from ai.common.schema import Question


class _FakeHost:
    llm = object()
    tools = object()
    memory = None


class _FakeInner:
    pipeId = 42

    def __init__(self) -> None:
        self.written = []

    def writeAnswers(self, answer: Any) -> None:
        self.written.append(answer)


class _FakeIInstance:
    def __init__(self) -> None:
        self._agent_host = _FakeHost()
        self.instance = _FakeInner()


class _Driver(AgentBase):
    FRAMEWORK = 'stub'

    def _run(self, *, context: AgentContext, question: Question) -> Tuple[str, Any]:
        return ('answer text', {'raw': True})


def test_run_agent_carries_question_metadata_to_emitted_answer():
    driver = _Driver.__new__(_Driver)
    driver._instructions = []
    driver._agent_description = ''
    i_instance = _FakeIInstance()
    question = Question()
    question.metadata = {'expected': 'reference answer'}

    driver.run_agent(i_instance, question, emit_answers_lane=True)

    assert len(i_instance.instance.written) == 1
    assert i_instance.instance.written[0].metadata == {'expected': 'reference answer'}
