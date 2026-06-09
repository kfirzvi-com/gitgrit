"""A small, reusable in-process agentic LLM loop.

Generalised from the in-sandbox policy loop (``sandbox_image/llm.py``): the
model is given tool schemas, decides for itself what to inspect, we execute the
tools and feed results back until it returns a structured (Pydantic) result.

Unlike the policy loop this runs in-process (e.g. in the background worker), so
the caller passes a plain object whose ``@tool``-marked methods back the tools.
Those methods may touch the network/DB directly — there's no sandbox boundary,
because this loop only reads (config files, etc.) and never executes untrusted
code.
"""
from __future__ import annotations

import inspect
import json
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
            except _RateLimitError:
                attempt += 1
                if attempt > RATE_LIMIT_RETRIES:
                    raise
                wait = 20 * attempt
                self._emit(
                    f"rate limited; retrying in {wait}s "
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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(_truncate_for_model(result)),
                    }
                )

            if tool_calls_made >= MAX_TOOL_CALLS:
                break

        # Force a structured final answer (no tools on this call).
        messages.append(
            {
                "role": "user",
                "content": "Provide your final answer now as the structured response.",
            }
        )
        final = self._complete(messages, response_format=response_model)
        content = final.choices[0].message.content
        return response_model.model_validate_json(content)
