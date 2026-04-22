from typing import Callable

_tools: list[Callable] = []
_prompts: list[Callable] = []


def register(fn: Callable) -> Callable:
    _tools.append(fn)
    return fn


def register_prompt(fn: Callable) -> Callable:
    _prompts.append(fn)
    return fn


def apply_all(mcp_instance) -> None:
    for fn in _tools:
        mcp_instance.tool()(fn)


def apply_all_prompts(mcp_instance) -> None:
    for fn in _prompts:
        mcp_instance.prompt()(fn)
