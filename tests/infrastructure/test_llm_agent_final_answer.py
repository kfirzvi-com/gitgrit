"""The agent's final answer: plain JSON text, never provider JSON mode."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
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
        # The agent reuses one messages list for every call; snapshot it so
        # each recorded call shows what was sent at that moment.
        calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return replies.pop(0)

    with patch.object(llm_agent.litellm, "completion", side_effect=fake):
        result = LLMAgent(model="gemini/x").run(
            toolbox=Box(), system_prompt="s", instructions="i", response_model=Answer
        )
    return result, calls


class FinalAnswerTests(SimpleTestCase):
    def test_final_answer_is_plain_json_without_response_format(self):
        result, calls = _run([_reply("done"), _reply('{"name": "api", "kind": "service"}')])
        assert result == Answer(name="api", kind="service")
        final = calls[-1]
        assert "response_format" not in final
        assert final["max_tokens"] == FINAL_MAX_TOKENS
        prompt = final["messages"][-1]["content"]
        assert "JSON Schema" in prompt and '"name"' in prompt

    def test_code_fence_and_prose_are_stripped(self):
        assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert _extract_json('Here it is: {"a": {"b": 2}} hope that helps') == '{"a": {"b": 2}}'
        with self.assertRaises(ValueError):
            _extract_json("no json here")
        with self.assertRaises(ValueError):
            _extract_json(None)

    def test_invalid_answer_gets_one_repair_turn(self):
        result, calls = _run([_reply("done"), _reply('{"kind": "service"}'), _reply('{"name": "api"}')])
        assert result.name == "api"
        repair = calls[-1]["messages"][-1]["content"]
        assert "rejected" in repair and "not valid" in repair

    def test_cut_off_answer_is_retried_then_fails_fast(self):
        long = _reply('{"name": "a' + "x" * 50, finish_reason="length")
        with self.assertRaisesRegex(FinalAnswerError, "token limit"):
            _run([_reply("done"), long, _reply('{"name": "b', finish_reason="length")])

    def test_empty_content_is_treated_as_invalid(self):
        result, _ = _run([_reply("done"), _reply(None), _reply('{"name": "x"}')])
        assert result.name == "x"

    def test_final_answer_keeps_the_loop_tools_but_forbids_calling_them(self):
        """Real capture, prod 2026-10-14: Anthropic signs each thinking block
        against the ``tools`` list of the request that produced it. The final
        call used to drop ``tools`` (LiteLLM then adds a dummy tool), so every
        map on a newer Anthropic account died with a 400 "Invalid `signature` in
        `thinking` block ... The `tools` list differs"."""
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="read", arguments='{"path": "a.txt"}'))
        _, calls = _run([_reply(None, tool_calls=[call]), _reply("done"), _reply('{"name": "n"}')])
        loop, final = calls[0], calls[-1]
        assert final["tools"] == loop["tools"]
        assert final["tool_choice"] == "none"
        assert loop["tool_choice"] == "auto"
        # Bedrock rejects tool_choice="none" unless LiteLLM may drop it.
        assert final["drop_params"] is True

    def test_final_reply_that_calls_a_tool_gets_the_repair_turn(self):
        """Providers where tool_choice was dropped (Bedrock, Ollama) may still
        call a tool; that is a rejected answer, never a return to the loop."""
        call = SimpleNamespace(id="c2", function=SimpleNamespace(name="read", arguments="{}"))
        result, calls = _run([_reply("done"), _reply(None, tool_calls=[call]), _reply('{"name": "n"}')])
        assert result.name == "n"
        assert len(calls) == 3
        assert "called a tool" in calls[-1]["messages"][-1]["content"]

    def test_tool_loop_still_runs_before_the_final_answer(self):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="read", arguments='{"path": "a.txt"}'))
        result, calls = _run([_reply(None, tool_calls=[call]), _reply("done"), _reply('{"name": "n"}')])
        assert result.name == "n"
        tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
        assert tool_msg["content"] == "contents of a.txt"



# --- bounds and request shape of the final phase ----------------------------


class CountingBox(Box):
    """``Box`` that counts how many times the model's tool actually ran."""

    def __init__(self):
        self.reads = 0

    @tool
    def read(self, path: str):
        """Read a file."""
        self.reads += 1
        return super().read(path)


def _tool_call(n):
    return SimpleNamespace(id=f"c{n}", function=SimpleNamespace(name="read", arguments='{"path": "a.txt"}'))


def _run_counting(replies):
    """Like ``_run`` but with ``CountingBox``; each recorded call also carries
    how many tool executions had happened when it was sent."""
    box = CountingBox()
    calls = []

    def fake(**kwargs):
        calls.append(({**kwargs, "messages": list(kwargs["messages"])}, box.reads))
        return replies.pop(0)

    with patch.object(llm_agent.litellm, "completion", side_effect=fake):
        result = LLMAgent(model="gemini/x").run(
            toolbox=box, system_prompt="s", instructions="i", response_model=Answer
        )
    return result, calls, box


class FinalPhaseBoundsTests(SimpleTestCase):
    def test_run_is_bounded_when_the_model_never_stops_calling_tools(self):
        """Worst case: every reply, loop and final, calls a tool. The run must end
        after MAX_ITERATIONS + FINAL_ANSWER_ATTEMPTS completions, and the final
        phase must never execute a tool or re-enter the loop."""
        replies = [_reply(None, tool_calls=[_tool_call(i)]) for i in range(llm_agent.MAX_ITERATIONS + llm_agent.FINAL_ANSWER_ATTEMPTS + 5)]
        box = CountingBox()
        calls = []

        def fake(**kwargs):
            calls.append((kwargs, box.reads))
            return replies.pop(0)

        with patch.object(llm_agent.litellm, "completion", side_effect=fake), self.assertRaisesRegex(
            FinalAnswerError, "called a tool"
        ):
            LLMAgent(model="gemini/x").run(toolbox=box, system_prompt="s", instructions="i", response_model=Answer)

        assert len(calls) == llm_agent.MAX_ITERATIONS + llm_agent.FINAL_ANSWER_ATTEMPTS == 14
        assert box.reads <= llm_agent.MAX_TOOL_CALLS
        final_calls = calls[-llm_agent.FINAL_ANSWER_ATTEMPTS :]
        assert [kw["tool_choice"] for kw, _ in final_calls] == ["none", "none"]
        # No tool ran once the final phase started: the count seen by the first
        # final call equals the count at the end of the run.
        assert final_calls[0][1] == box.reads

    def test_tool_call_cap_stops_the_loop_and_still_sends_the_final_call(self):
        """One reply with 26 tool calls hits MAX_TOOL_CALLS in iteration 1; the
        loop stops there, the extra call is never run, and the final call still
        goes out with the loop's tools."""
        burst = _reply(None, tool_calls=[_tool_call(i) for i in range(llm_agent.MAX_TOOL_CALLS + 1)])
        result, calls, box = _run_counting([burst, _reply('{"name": "capped"}')])
        assert result.name == "capped"
        assert box.reads == llm_agent.MAX_TOOL_CALLS
        assert len(calls) == 2
        loop, final = calls[0][0], calls[1][0]
        assert final["tools"] == loop["tools"]
        assert final["tool_choice"] == "none"

    def test_repair_call_carries_the_same_tools_and_no_tool_role(self):
        """The repair turn must look to the provider exactly like the first final
        call (same tools, tool_choice none) and must add only an assistant + user
        message, never a tool result with a dangling tool_call_id."""
        _, calls = _run([_reply("done"), _reply("not json"), _reply('{"name": "n"}')])
        loop, first, repair = calls
        for final in (first, repair):
            assert final["tools"] == loop["tools"]
            assert final["tool_choice"] == "none"
            assert final["drop_params"] is True
        appended = repair["messages"][len(first["messages"]) :]
        assert [m["role"] for m in appended] == ["assistant", "user"]
        assert not any(m.get("role") == "tool" for m in repair["messages"])

    def test_loop_calls_are_unchanged_by_the_final_answer_fix(self):
        """Guards against the final-call settings leaking into the tool loop."""
        _, calls = _run([_reply(None, tool_calls=[_tool_call(1)]), _reply("done"), _reply('{"name": "n"}')])
        loop_calls = calls[:-1]
        assert len(loop_calls) == 2
        for kw in loop_calls:
            assert kw["tool_choice"] == "auto"
            assert "max_tokens" not in kw
            assert "drop_params" not in kw

    def test_empty_content_tool_call_final_reply_appends_an_empty_assistant_message(self):
        """Bedrock/Ollama (tool_choice dropped) may answer the final prompt with a
        tool call and no text. Pins current behavior: the repair turn echoes the
        rejected reply as an assistant message with content "" (the tool call
        itself is not kept). Some providers reject empty assistant content; if
        that is ever fixed, update this assertion (plan risk R1)."""
        result, calls = _run([_reply("done"), _reply(None, tool_calls=[_tool_call(9)]), _reply('{"name": "n"}')])
        assert result.name == "n"
        first, repair = calls[1], calls[2]
        appended = repair["messages"][len(first["messages"]) :]
        assert appended[0] == {"role": "assistant", "content": ""}
        assert appended[1]["role"] == "user"

    def test_tool_calls_past_the_cap_still_get_a_tool_result(self):
        """Staging 2026-10-15 (Haiku 5.5, gitgrit repo): when the cap is reached in
        the middle of a reply that carries several tool calls, the extra calls got
        no ``tool`` message, and Anthropic rejected the next request with 400
        "tool_use ids were found without tool_result blocks". Every requested
        call must be answered, even if only to say it was not run."""
        burst = _reply(None, tool_calls=[_tool_call(i) for i in range(llm_agent.MAX_TOOL_CALLS + 2)])
        result, calls, box = _run_counting([burst, _reply('{"name": "capped"}')])
        assert result.name == "capped"
        assert box.reads == llm_agent.MAX_TOOL_CALLS
        final_messages = calls[-1][0]["messages"]
        answered = [m for m in final_messages if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in answered] == [f"c{i}" for i in range(llm_agent.MAX_TOOL_CALLS + 2)]
        skipped = answered[llm_agent.MAX_TOOL_CALLS:]
        assert all("not executed" in m["content"] for m in skipped)
        assert all("not executed" not in m["content"] for m in answered[: llm_agent.MAX_TOOL_CALLS])



# --- rate limits ------------------------------------------------------------

GEMINI_QUOTA_AS_400 = (
    'litellm.BadRequestError: GeminiException BadRequestError - { "error": { "code": 429, '
    '"message": "You exceeded your current quota ... limit: 15, model: gemini-3.1-flash-lite\\n'
    'Please retry in 47.540714403s.", "status": "RESOURCE_EXHAUSTED" } }'
)


class RateLimitTests(SimpleTestCase):
    def test_gemini_quota_429_labelled_400_is_retried_after_the_advised_wait(self):
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

    def test_real_bad_request_is_not_retried(self):
        import litellm.exceptions as ex

        err = ex.BadRequestError(message='{"error": {"code": 400, "message": "bad"}}', llm_provider="gemini", model="gemini/x")
        with patch.object(llm_agent.litellm, "completion", side_effect=err), patch.object(
            llm_agent.time, "sleep"
        ) as sleep, self.assertRaises(ex.BadRequestError):
            LLMAgent(model="gemini/x").run(toolbox=Box(), system_prompt="s", instructions="i", response_model=Answer)
        sleep.assert_not_called()

    def test_retry_wait_falls_back_and_is_capped(self):
        assert llm_agent._retry_wait(Exception("no hint"), 2) == 40
        assert llm_agent._retry_wait(Exception("Please retry in 300s."), 1) == llm_agent.RATE_LIMIT_MAX_WAIT
