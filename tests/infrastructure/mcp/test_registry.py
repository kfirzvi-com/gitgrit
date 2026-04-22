from unittest.mock import MagicMock

from app.infrastructure.mcp.registry import (
    _prompts,
    _tools,
    apply_all,
    apply_all_prompts,
    register,
    register_prompt,
)


def test_register_returns_original_function():
    def _fn():
        pass

    result = register(_fn)
    assert result is _fn
    _tools.remove(_fn)


def test_register_adds_to_tools_list():
    def _fn():
        pass

    before = len(_tools)
    register(_fn)
    assert len(_tools) == before + 1
    assert _fn in _tools
    _tools.remove(_fn)


def test_register_prompt_returns_original_function():
    def _fn():
        pass

    result = register_prompt(_fn)
    assert result is _fn
    _prompts.remove(_fn)


def test_register_prompt_adds_to_prompts_list():
    def _fn():
        pass

    before = len(_prompts)
    register_prompt(_fn)
    assert len(_prompts) == before + 1
    assert _fn in _prompts
    _prompts.remove(_fn)


def test_apply_all_calls_mcp_tool_for_each_registered_fn():
    mcp = MagicMock()
    apply_all(mcp)
    assert mcp.tool.call_count == len(_tools)


def test_apply_all_prompts_calls_mcp_prompt_for_each_fn():
    mcp = MagicMock()
    apply_all_prompts(mcp)
    assert mcp.prompt.call_count == len(_prompts)
