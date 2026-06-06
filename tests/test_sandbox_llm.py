"""Unit tests for the in-sandbox LLM agentic loop (sandbox_image/llm.py).

litellm is not an app dependency — it lives only in the sandbox image — so we
stub it into sys.modules before importing the module under test. No real model
is ever called; we script the completion responses and a MockProvider repo.
"""
import json
import sys
import types
from pathlib import Path

import pytest

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"


# --- Fakes mimicking the litellm response shape ---------------------------


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _Fn(name, arguments)


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        return {"role": "assistant", "content": self.content, "tool_calls": []}


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _Choice:
    def __init__(self, message):
        self.message = message


class _Response:
    def __init__(self, message, usage):
        self.choices = [_Choice(message)]
        self.usage = usage


class ScriptedCompletion:
    """Stands in for litellm.completion: one tool call, then stops; the final
    (response_format) call returns the scripted structured verdict."""

    def __init__(self, final_json):
        self.calls = []
        self._final_json = final_json

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            return _Response(_Message(content=self._final_json), _Usage(10, 5))
        loop_n = sum(1 for c in self.calls if "response_format" not in c)
        if loop_n == 1:
            tc = _ToolCall("call_1", "list_files", "{}")
            return _Response(_Message(tool_calls=[tc]), _Usage(20, 8))
        return _Response(_Message(content="enough evidence"), _Usage(5, 2))


class AlwaysToolCompletion:
    """Never stops asking for a tool — exercises the MAX_ITERATIONS cap."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            return _Response(
                _Message(
                    content=json.dumps(
                        {"passed": False, "reason": "looped", "violations": []}
                    )
                ),
                _Usage(1, 1),
            )
        tc = _ToolCall("c", "list_files", "{}")
        return _Response(_Message(tool_calls=[tc]), _Usage(1, 1))


def _load_llm(completion):
    fake = types.ModuleType("litellm")
    fake.completion = completion
    sys.modules["litellm"] = fake
    if str(SANDBOX_DIR) not in sys.path:
        sys.path.insert(0, str(SANDBOX_DIR))
    sys.modules.pop("llm", None)
    import llm

    return llm


def _mock_project():
    from project_context import ProjectContext
    from providers.factory import create_provider

    return ProjectContext(create_provider("mock", "p", None))


def test_loop_runs_tools_and_returns_structured_verdict():
    scripted = ScriptedCompletion(
        json.dumps({"passed": True, "reason": "Docs are clear", "violations": []})
    )
    llm_mod = _load_llm(scripted)

    obj = llm_mod.LLM(
        {"reasoning": {"model": "anthropic/claude-x", "base_url": "", "api_key": "k"}},
        _mock_project(),
    )
    verdict = obj.reasoning.evaluate("Check docs")

    assert verdict.passed is True
    assert verdict.reason == "Docs are clear"
    # two loop calls (tool, then stop) + one final structured call
    assert obj.usage["calls"] == 3
    assert obj.usage["total_tokens"] == 50
    # the list_files tool result was fed back into the conversation
    final_messages = scripted.calls[-1]["messages"]
    assert any(m.get("role") == "tool" for m in final_messages)


def test_unconfigured_role_raises():
    llm_mod = _load_llm(
        ScriptedCompletion(
            json.dumps({"passed": True, "reason": "x", "violations": []})
        )
    )
    obj = llm_mod.LLM(
        {"reasoning": {"model": "m", "base_url": "", "api_key": "k"}}, _mock_project()
    )
    with pytest.raises(llm_mod.LLMRoleNotConfigured):
        obj.code.evaluate("nope")


def test_loop_respects_max_iterations():
    always = AlwaysToolCompletion()
    llm_mod = _load_llm(always)

    obj = llm_mod.LLM(
        {"reasoning": {"model": "m", "base_url": "", "api_key": "k"}}, _mock_project()
    )
    verdict = obj.reasoning.evaluate("loop forever")

    loop_calls = sum(1 for c in always.calls if "response_format" not in c)
    assert loop_calls == llm_mod.MAX_ITERATIONS
    assert verdict.passed is False
