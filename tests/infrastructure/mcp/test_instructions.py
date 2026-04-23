from app.infrastructure.mcp.instructions import build_instructions
from app.infrastructure.mcp.registry import _tools


def test_returns_non_empty_string():
    result = build_instructions()
    assert isinstance(result, str)
    assert len(result) > 0


def test_contains_registered_tool_names():
    result = build_instructions()
    for fn in _tools:
        assert fn.__name__ in result, f"Tool '{fn.__name__}' missing from instructions"


def test_contains_required_sections():
    result = build_instructions()
    assert "## Core Concepts" in result
    assert "Policy Code Contract" in result
    assert "Workflow" in result
    assert "## Tool Reference" in result
    assert "## Critical Rules" in result


def test_tool_reference_has_table_header():
    result = build_instructions()
    assert "| Tool |" in result
