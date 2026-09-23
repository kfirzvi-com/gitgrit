"""The agent's final answer: plain JSON text, never provider JSON mode."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from app.infrastructure import llm_agent
from app.infrastructure.llm_agent import (
    FINAL_MAX_TOKENS,
    FinalAnswerError,
    LLMAgent,
    _extract_json,
    tool,
)


class Answer(BaseModel):
    name: str
    kind: str = "other"


class Box:
    @tool
    def read(self, path: str):
        """Read a file."""
        return f"contents of {path}"


def _reply(content=None, tool_calls=None, finish_reason="stop"):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    msg.model_dump = lambda: {"role": "assistant", "content": content, "tool_calls": []}
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)], usage=None)


def _run(replies):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return replies.pop(0)

    with patch.object(llm_agent.litellm, "completion", side_effect=fake):
        result = LLMAgent(model="gemini/x").run(
            toolbox=Box(), system_prompt="s", instructions="i", response_model=Answer
        )
    return result, calls


def test_final_answer_is_plain_json_without_response_format():
    result, calls = _run([_reply("done"), _reply('{"name": "api", "kind": "service"}')])
    assert result == Answer(name="api", kind="service")
    final = calls[-1]
    assert "response_format" not in final
    assert "tools" not in final
    assert final["max_tokens"] == FINAL_MAX_TOKENS
    prompt = final["messages"][-1]["content"]
    assert "JSON Schema" in prompt and '"name"' in prompt


def test_code_fence_and_prose_are_stripped():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('Here it is: {"a": {"b": 2}} hope that helps') == '{"a": {"b": 2}}'
    with pytest.raises(ValueError):
        _extract_json("no json here")
    with pytest.raises(ValueError):
        _extract_json(None)


def test_invalid_answer_gets_one_repair_turn():
    result, calls = _run([_reply("done"), _reply('{"kind": "service"}'), _reply('{"name": "api"}')])
    assert result.name == "api"
    repair = calls[-1]["messages"][-1]["content"]
    assert "rejected" in repair and "not valid" in repair


def test_cut_off_answer_is_retried_then_fails_fast():
    long = _reply('{"name": "a' + "x" * 50, finish_reason="length")
    with pytest.raises(FinalAnswerError, match="token limit"):
        _run([_reply("done"), long, _reply('{"name": "b', finish_reason="length")])


def test_empty_content_is_treated_as_invalid():
    result, _ = _run([_reply("done"), _reply(None), _reply('{"name": "x"}')])
    assert result.name == "x"


def test_tool_loop_still_runs_before_the_final_answer():
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="read", arguments='{"path": "a.txt"}'))
    result, calls = _run([_reply(None, tool_calls=[call]), _reply("done"), _reply('{"name": "n"}')])
    assert result.name == "n"
    tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
    assert tool_msg["content"] == "contents of a.txt"


# --- rate limits ------------------------------------------------------------

GEMINI_QUOTA_AS_400 = (
    'litellm.BadRequestError: GeminiException BadRequestError - { "error": { "code": 429, '
    '"message": "You exceeded your current quota ... limit: 15, model: gemini-3.1-flash-lite\\n'
    'Please retry in 47.540714403s.", "status": "RESOURCE_EXHAUSTED" } }'
)


def test_gemini_quota_429_labelled_400_is_retried_after_the_advised_wait():
    """Real capture 2026-09-23: LiteLLM raised Gemini's per-minute 429 as
    BadRequestError, which skipped the retry and failed the whole map."""
    import litellm.exceptions as ex

    err = ex.BadRequestError(message=GEMINI_QUOTA_AS_400, llm_provider="gemini", model="gemini/x")
    replies = [err, _reply("done"), _reply('{"name": "ok"}')]

    def fake(**kwargs):
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with patch.object(llm_agent.litellm, "completion", side_effect=fake), patch.object(
        llm_agent.time, "sleep"
    ) as sleep:
        result = LLMAgent(model="gemini/x").run(
            toolbox=Box(), system_prompt="s", instructions="i", response_model=Answer
        )
    assert result.name == "ok"
    sleep.assert_called_once()
    assert 48 <= sleep.call_args.args[0] <= 49


def test_real_bad_request_is_not_retried():
    import litellm.exceptions as ex

    err = ex.BadRequestError(message='{"error": {"code": 400, "message": "bad"}}', llm_provider="gemini", model="gemini/x")
    with patch.object(llm_agent.litellm, "completion", side_effect=err), patch.object(
        llm_agent.time, "sleep"
    ) as sleep, pytest.raises(ex.BadRequestError):
        LLMAgent(model="gemini/x").run(toolbox=Box(), system_prompt="s", instructions="i", response_model=Answer)
    sleep.assert_not_called()


def test_retry_wait_falls_back_and_is_capped():
    assert llm_agent._retry_wait(Exception("no hint"), 2) == 40
    assert llm_agent._retry_wait(Exception("Please retry in 300s."), 1) == llm_agent.RATE_LIMIT_MAX_WAIT
