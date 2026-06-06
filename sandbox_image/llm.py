"""LLM support for policies — runs entirely inside the sandbox.

Exposes an ``llm`` object to policy authors with a fixed set of role
attributes (``llm.reasoning``, ``llm.code``). Each role runs an agentic loop:
the model is given tools bound to the token-bearing ``ProjectContext`` and
decides for itself what to inspect; we execute the tools and feed the results
back until the model returns a structured verdict.

Security boundary: the model never sees the repo access token. It only ever
sees tool *signatures* (JSON schemas) and tool *results*. The closure over
``project`` — which holds the token — is the only thing that touches the repo.
"""
from __future__ import annotations

import json

import litellm
from pydantic import BaseModel

# Hard guardrails. A confused model must not loop forever or run up a bill.
# These also seed the future per-workspace token-budget feature.
MAX_ITERATIONS = 12  # model round-trips per evaluate()
MAX_TOOL_CALLS = 40  # total tool executions per evaluate()

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


def make_project_tools(project):
    """Return ``(tool_schemas, dispatch)`` bound to a ``ProjectContext``.

    ``tool_schemas`` is the OpenAI-style function list handed to the model;
    ``dispatch`` maps tool name → a callable closed over ``project``. The model
    sees only the schemas, never ``project`` or its token.
    """
    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List every file path in the repository.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_content",
                "description": (
                    "Read the full contents of a file. Returns null if the file "
                    "does not exist."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Repository-relative file path.",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_languages",
                "description": "Return detected languages and their percentages.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_metadata",
                "description": (
                    "Return repository metadata (name, description, default "
                    "branch, topics, etc.)."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]

    dispatch = {
        "list_files": lambda **_: project.list_files(),
        "get_file_content": lambda path, **_: project.get_file_content(path),
        "get_languages": lambda **_: project.get_languages(),
        "get_metadata": lambda **_: project.get_metadata(),
    }
    return tool_schemas, dispatch


class _RoleRunner:
    """Runs the agentic loop for one role. Accumulates token usage into the
    shared ``usage`` dict owned by the parent ``LLM`` so the entrypoint can
    report totals regardless of how many roles a policy touches."""

    def __init__(self, model, base_url, api_key, project, usage):
        self._model = model
        self._base_url = base_url or None
        self._api_key = api_key or None
        self._project = project
        self._usage = usage

    def _complete(self, messages, **kwargs):
        resp = litellm.completion(
            model=self._model,
            messages=messages,
            api_base=self._base_url,
            api_key=self._api_key,
            **kwargs,
        )
        u = getattr(resp, "usage", None)
        if u:
            self._usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
            self._usage["total_tokens"] += getattr(u, "total_tokens", 0) or 0
        self._usage["calls"] += 1
        return resp

    def evaluate(self, instructions, response_model=PolicyVerdict):
        """Run the loop, then return a validated ``response_model`` instance."""
        tool_schemas, dispatch = make_project_tools(self._project)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": instructions},
        ]

        tool_calls_made = 0
        for _ in range(MAX_ITERATIONS):
            resp = self._complete(messages, tools=tool_schemas, tool_choice="auto")
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                break

            # Record the assistant turn that requested the tools.
            messages.append(
                msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
            )

            for call in tool_calls:
                if tool_calls_made >= MAX_TOOL_CALLS:
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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
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
        return response_model.model_validate_json(content)


class LLM:
    """The object passed to policies as ``llm``. Roles are a fixed, static set
    — the workspace assigns a provider+model to each, but cannot add new ones."""

    def __init__(self, roles_config, project):
        # roles_config: {"reasoning": {"model","base_url","api_key"}, "code": {...}}
        self._roles_config = roles_config or {}
        self._project = project
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
            cfg["model"],
            cfg.get("base_url"),
            cfg.get("api_key"),
            self._project,
            self.usage,
        )

    @property
    def reasoning(self):
        return self._role("reasoning")

    @property
    def code(self):
        return self._role("code")
