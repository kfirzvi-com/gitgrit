"""LLM support for policies — runs entirely inside the sandbox.

Exposes an ``llm`` object to policy authors with a fixed set of role
attributes (``llm.reasoning``, ``llm.code``). Each role runs an agentic loop:
the model is given tools bound to the token-bearing ``ProjectContext`` and
decides for itself what to inspect; we execute the tools and feed the results
back until the model returns a structured verdict.

Security boundary: the model never sees the repo access token. It only ever
sees tool *signatures* (JSON schemas) and tool *results*. The closure over
``project`` — which holds the token — is the only thing that touches the repo.

The loop logs its process (role/model, each tool call, token usage, the final
verdict) into the run's PolicyLogger so authors can see what the model did when
a policy fails.
"""
from __future__ import annotations

import inspect
import json
import time

import litellm
from pydantic import BaseModel

try:
    from litellm.exceptions import RateLimitError as _RateLimitError
except Exception:  # litellm is stubbed in unit tests
    class _RateLimitError(Exception):
        pass

# Hard guardrails. A confused model must not loop forever or run up a bill.
# These also seed the future per-workspace token-budget feature. The caps also
# keep cumulative input tokens down: every call re-sends the whole conversation,
# so reading fewer/smaller files is what keeps us under provider rate limits.
MAX_ITERATIONS = 12  # model round-trips per evaluate()
MAX_TOOL_CALLS = 20  # total tool executions per evaluate()
MAX_TOOL_RESULT_CHARS = 6000  # cap each tool result fed back to the model
RATE_LIMIT_RETRIES = 3  # retry transient 429s with linear backoff

_SYSTEM_PROMPT = (
    "You are evaluating a software repository against an engineering standard. "
    "Use the provided tools to inspect the repository yourself: list files, read "
    "the ones that matter, and gather enough concrete evidence to make a fair "
    "judgment. Do not assume — verify by reading. When you have enough evidence, "
    "stop calling tools and return your final structured verdict."
)


class PolicyVerdict(BaseModel):
    """Default structured result authors get back from ``role.evaluate``."""

    passed: bool
    reason: str
    violations: list[str] = []


class LLMRoleNotConfigured(RuntimeError):
    """Raised when a policy uses a role the workspace hasn't configured."""


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

    Understands ``typing.Annotated[T, "description"]`` and unwraps optionals /
    unions (``T | None``) to their first concrete type."""
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
    """Build an OpenAI-style function schema from a ProjectContext method's
    signature and docstring."""
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


def make_project_tools(project):
    """Return ``(tool_schemas, dispatch)`` derived from the ``@tool``-marked
    methods on ``project`` (a ProjectContext).

    The schemas are generated from each method's signature + docstring, so the
    tool set is always in sync with ProjectContext — adding a documented,
    ``@tool``-marked method is all it takes to expose a new tool. The model
    sees only the schemas, never ``project`` or its token.
    """
    schemas = []
    dispatch = {}
    for name, member in inspect.getmembers(project, predicate=callable):
        if getattr(member, "__llm_tool__", False):
            schemas.append(_tool_schema(name, member))
            dispatch[name] = _make_caller(member)
    return schemas, dispatch


def _summarize(value):
    """Short, log-friendly description of a tool result (never the full payload)."""
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
    """Cap a tool result before sending it to the model. Large file contents
    would otherwise accumulate in the conversation and blow provider rate
    limits, since every call re-sends the whole history."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"\n…[truncated {len(value) - limit} chars]"
    return value


class _RoleRunner:
    """Runs the agentic loop for one role. Accumulates token usage into the
    shared ``usage`` dict owned by the parent ``LLM`` so the entrypoint can
    report totals regardless of how many roles a policy touches, and records
    its process into the optional logger."""

    def __init__(self, role_name, model, base_url, api_key, project, usage, logger):
        self._role_name = role_name
        self._model = model
        self._base_url = base_url or None
        self._api_key = api_key or None
        self._project = project
        self._usage = usage
        self._logger = logger

    def _emit(self, message):
        if self._logger is not None:
            self._logger.info(message)

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
                if self._logger is not None:
                    self._logger.warning(
                        f"rate limited by provider; retrying in {wait}s "
                        f"(attempt {attempt}/{RATE_LIMIT_RETRIES})"
                    )
                time.sleep(wait)
        u = getattr(resp, "usage", None)
        if u:
            self._usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
            self._usage["total_tokens"] += getattr(u, "total_tokens", 0) or 0
        self._usage["calls"] += 1
        return resp

    def evaluate(self, instructions, response_model=PolicyVerdict):
        """Run the loop, then return a validated ``response_model`` instance."""
        self._emit(f"llm.{self._role_name}: starting evaluation with {self._model}")
        tool_schemas, dispatch = make_project_tools(self._project)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
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

            # Record the assistant turn that requested the tools.
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
                "content": "Provide your final verdict now as the structured response.",
            }
        )
        final = self._complete(messages, response_format=response_model)
        content = final.choices[0].message.content
        verdict = response_model.model_validate_json(content)
        passed = getattr(verdict, "passed", None)
        self._emit(
            f"llm.{self._role_name}: verdict passed={passed} "
            f"({self._usage['total_tokens']} tokens, {self._usage['calls']} calls)"
        )
        return verdict


class LLM:
    """The object passed to policies as ``llm``. Roles are a fixed, static set
    — the workspace assigns a provider+model to each, but cannot add new ones."""

    def __init__(self, roles_config, project, logger=None):
        # roles_config: {"reasoning": {"model","base_url","api_key"}, "code": {...}}
        self._roles_config = roles_config or {}
        self._project = project
        self._logger = logger
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

    def _role(self, name):
        cfg = self._roles_config.get(name)
        if not cfg:
            raise LLMRoleNotConfigured(
                f"LLM role '{name}' is not configured for this workspace. "
                f"Configure it under Workspace Settings → LLM."
            )
        return _RoleRunner(
            name,
            cfg["model"],
            cfg.get("base_url"),
            cfg.get("api_key"),
            self._project,
            self.usage,
            self._logger,
        )

    @property
    def reasoning(self):
        return self._role("reasoning")

    @property
    def code(self):
        return self._role("code")
