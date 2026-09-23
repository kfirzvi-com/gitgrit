"""A small, reusable in-process agentic LLM loop.

Generalised from the in-sandbox standard loop (``sandbox_image/llm.py``): the
model is given tool schemas, decides for itself what to inspect, we execute the
tools and feed results back until it returns a structured (Pydantic) result.

The final answer is requested as plain JSON text (schema in the prompt), not
through the provider's JSON mode (``response_format``). On Gemini, LiteLLM maps
``response_format`` to Gemini's constrained decoding, and the Lite models
degrade badly under it: in staging runs on 2026-09-23 it collapsed monorepo
maps to one component, emitted hundreds of invented technologies, blanked
every kind/description, or ran to the output cap. The same conversation asked
for plain JSON answered cleanly every time. Plain text works on every provider,
so there is one code path.

Unlike the standard loop this runs in-process (e.g. in the background worker), so
the caller passes a plain object whose ``@tool``-marked methods back the tools.
Those methods may touch the network/DB directly — there's no sandbox boundary,
because this loop only reads (config files, etc.) and never executes untrusted
code.
"""
from __future__ import annotations

import inspect
import json
import re
import time

import litellm

try:
    from litellm.exceptions import RateLimitError as _RateLimitError
except Exception:  # pragma: no cover - litellm may be stubbed in tests
    class _RateLimitError(Exception):
        pass

# Hard guardrails — a confused model must not loop forever or run up a bill.
# Every call re-sends the whole conversation, so capping tool calls / result
# size is what keeps cumulative input tokens under provider rate limits.
MAX_ITERATIONS = 12  # model round-trips per run()
MAX_TOOL_CALLS = 25  # total tool executions per run()
MAX_TOOL_RESULT_CHARS = 8000  # cap each tool result fed back to the model
RATE_LIMIT_RETRIES = 3  # retry transient 429s with linear backoff
RATE_LIMIT_MAX_WAIT = 65  # seconds; Gemini free tier asks for up to ~60s
FINAL_MAX_TOKENS = 16000  # the final JSON answer; a runaway answer stops here
FINAL_ANSWER_ATTEMPTS = 2  # one repair turn when the JSON is invalid or cut off


class FinalAnswerError(RuntimeError):
    """The model never produced a valid final answer."""


_BODY_429 = re.compile(r'"code"\s*:\s*429\b')
_RETRY_IN = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)


def _is_rate_limited(exc):
    """A 429, however LiteLLM labels it. Gemini's per-minute quota 429 arrives
    as ``BadRequestError`` (status 400); its body still says ``"code": 429``."""
    return isinstance(exc, _RateLimitError) or bool(_BODY_429.search(str(exc)))


def _retry_wait(exc, attempt):
    """Seconds to wait: the provider's "retry in Ns" when given, else 20s per attempt."""
    m = _RETRY_IN.search(str(exc))
    wait = float(m.group(1)) + 1 if m else 20 * attempt
    return min(wait, RATE_LIMIT_MAX_WAIT)


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _extract_json(text):
    """Pull the JSON object out of a model reply: drop a code fence and any
    prose around the outermost ``{ … }``."""
    text = _FENCE.sub("", (text or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the reply")
    return text[start : end + 1]


def _final_answer_prompt(response_model):
    schema = json.dumps(response_model.model_json_schema(), separators=(",", ":"))
    return (
        "Provide your final answer now. Reply with ONLY one JSON object that "
        "matches this JSON Schema — no prose, no code fence, no tool calls. "
        "Fill every field you have evidence for.\n"
        f"JSON Schema: {schema}"
    )


def tool(method):
    """Mark a method as an LLM-callable tool."""
    method.__llm_tool__ = True
    return method


_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _annotation_info(annotation):
    """Return (json_type, description|None) for a parameter annotation.

    Understands ``typing.Annotated[T, "description"]`` and unwraps
    optionals/unions (``T | None``) to their first concrete type.
    """
    description = None
    if hasattr(annotation, "__metadata__"):  # typing.Annotated[T, "desc"]
        description = str(annotation.__metadata__[0])
        annotation = annotation.__origin__
    if annotation is inspect.Parameter.empty:
        return "string", description
    args = getattr(annotation, "__args__", None)
    if args:  # e.g. str | None -> str
        annotation = next((a for a in args if a is not type(None)), str)
    return _PY_TO_JSON.get(annotation, "string"), description


def _tool_schema(name, method):
    """Build an OpenAI-style function schema from a method signature + docstring."""
    properties = {}
    required = []
    for pname, param in inspect.signature(method).parameters.items():
        if pname == "self":
            continue
        json_type, description = _annotation_info(param.annotation)
        prop = {"type": json_type}
        if description:
            prop["description"] = description
        properties[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (inspect.getdoc(method) or "").strip(),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _make_caller(method):
    """Wrap a bound method so it ignores any kwargs the model invents."""
    valid = {p for p in inspect.signature(method).parameters if p != "self"}

    def call(**kwargs):
        return method(**{k: v for k, v in kwargs.items() if k in valid})

    return call


def make_tools(toolbox):
    """Return ``(schemas, dispatch)`` from the ``@tool``-marked methods on an object."""
    schemas = []
    dispatch = {}
    for name, member in inspect.getmembers(toolbox, predicate=callable):
        if getattr(member, "__llm_tool__", False):
            schemas.append(_tool_schema(name, member))
            dispatch[name] = _make_caller(member)
    return schemas, dispatch


def _summarize(value):
    if value is None:
        return "null"
    if isinstance(value, str):
        return f"{len(value)} chars"
    if isinstance(value, (list, tuple)):
        return f"{len(value)} items"
    if isinstance(value, dict):
        return f"{len(value)} keys"
    return type(value).__name__


def _truncate_for_model(value, limit=MAX_TOOL_RESULT_CHARS):
    if isinstance(value, (list, tuple)):
        # A list is re-sent on every later turn; cap it like any other result.
        value = "\n".join(str(v) for v in value)
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"\n…[truncated {len(value) - limit} chars]"
    return value


class LLMAgent:
    """Runs the agentic loop for one model, with a caller-supplied toolbox.

    ``usage`` accumulates token counts across the run so callers can persist
    cost. ``log`` is an optional callable ``(str) -> None`` for tracing.
    """

    def __init__(self, *, model, api_key=None, base_url=None, log=None):
        self._model = model
        self._api_key = api_key or None
        self._base_url = base_url or None
        self._log = log
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

    def _emit(self, message):
        if self._log is not None:
            self._log(message)

    def _complete(self, messages, **kwargs):
        attempt = 0
        while True:
            try:
                resp = litellm.completion(
                    model=self._model,
                    messages=messages,
                    api_base=self._base_url,
                    api_key=self._api_key,
                    **kwargs,
                )
                break
            except Exception as exc:
                if not _is_rate_limited(exc):
                    raise
                attempt += 1
                if attempt > RATE_LIMIT_RETRIES:
                    raise
                wait = _retry_wait(exc, attempt)
                self._emit(
                    f"rate limited; retrying in {wait:.0f}s "
                    f"(attempt {attempt}/{RATE_LIMIT_RETRIES})"
                )
                time.sleep(wait)
        u = getattr(resp, "usage", None)
        if u:
            self.usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            self.usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
            self.usage["total_tokens"] += getattr(u, "total_tokens", 0) or 0
        self.usage["calls"] += 1
        return resp

    def run(self, *, toolbox, system_prompt, instructions, response_model):
        """Drive the loop, then return a validated ``response_model`` instance."""
        tool_schemas, dispatch = make_tools(toolbox)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instructions},
        ]

        tool_calls_made = 0
        for i in range(MAX_ITERATIONS):
            resp = self._complete(messages, tools=tool_schemas, tool_choice="auto")
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                self._emit(f"iteration {i + 1}: model finished gathering evidence")
                break

            messages.append(
                msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
            )

            for call in tool_calls:
                if tool_calls_made >= MAX_TOOL_CALLS:
                    self._emit(f"reached tool-call cap ({MAX_TOOL_CALLS}); stopping")
                    break
                tool_calls_made += 1
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                fn = dispatch.get(name)
                try:
                    result = fn(**args) if fn else f"Unknown tool: {name}"
                except Exception as exc:  # tool errors are fed back, not fatal
                    result = f"Tool error: {exc}"
                arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                self._emit(f"tool: {name}({arg_str}) → {_summarize(result)}")
                payload = _truncate_for_model(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        # Text goes back verbatim: JSON-encoding a YAML/TOML file
                        # turns every newline into "\\n", which weak models misread.
                        "content": payload if isinstance(payload, str) else json.dumps(payload),
                    }
                )

            if tool_calls_made >= MAX_TOOL_CALLS:
                break

        return self._final_answer(messages, response_model)

    def _final_answer(self, messages, response_model):
        """Ask for the answer as plain JSON text and validate it.

        No ``tools`` and no ``response_format`` on these calls. A reply that is
        cut off (``finish_reason == "length"``), empty, or fails validation
        gets one repair turn quoting the problem; after that it raises
        ``FinalAnswerError`` so the caller's retry logic takes over quickly.
        """
        messages.append({"role": "user", "content": _final_answer_prompt(response_model)})
        problem = ""
        for attempt in range(1, FINAL_ANSWER_ATTEMPTS + 1):
            final = self._complete(messages, max_tokens=FINAL_MAX_TOKENS)
            choice = final.choices[0]
            content = getattr(choice.message, "content", None) or ""
            if getattr(choice, "finish_reason", None) == "length":
                problem = f"the answer hit the {FINAL_MAX_TOKENS}-token limit and was cut off"
            else:
                try:
                    return response_model.model_validate_json(_extract_json(content))
                except Exception as exc:  # ValueError, pydantic.ValidationError
                    problem = f"the answer was not valid: {str(exc)[:500]}"
            self._emit(f"final answer attempt {attempt} rejected: {problem}")
            if attempt < FINAL_ANSWER_ATTEMPTS:
                messages.append({"role": "assistant", "content": content[:2000]})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That reply was rejected: {problem}. Reply again with "
                            "ONLY the JSON object, shorter if needed, matching the schema."
                        ),
                    }
                )
        raise FinalAnswerError(f"no valid final answer after {FINAL_ANSWER_ATTEMPTS} attempts: {problem}")
