from app.infrastructure.mcp.instructions import (
    build_instructions,
    select_instructions,
)

# MCP `instructions` are injected into the system prompt and truncated by the
# client. Claude Code drops everything past ~1.9k chars; we cap at 1.9k.
_LENGTH_CAP = 1900


def test_returns_non_empty_string():
    result = build_instructions()
    assert isinstance(result, str)
    assert len(result) > 0


def test_default_flavor_is_claude():
    assert build_instructions() == select_instructions("claude")


def test_both_flavors_under_length_cap():
    """Regression guard: both flavors must fit under the client-side cap so
    nothing is silently dropped before reaching the model."""
    for kind in ("claude", "generic"):
        text = select_instructions(kind)
        assert len(text) <= _LENGTH_CAP, (
            f"{kind} instructions are {len(text)} chars, "
            f"over the {_LENGTH_CAP}-char cap."
        )


def test_both_flavors_have_core_concepts():
    for kind in ("claude", "generic"):
        text = select_instructions(kind)
        assert "## Core concepts" in text
        assert "**Policy**" in text
        assert "**Project**" in text


def test_both_flavors_carry_no_invented_enforcement_rule():
    """Hard guardrail: the model must never enforce a rule that didn't come
    from `validate_edit` for this project. The hooks and skills repeat this,
    but it must also live in the always-loaded MCP instructions."""
    for kind in ("claude", "generic"):
        text = select_instructions(kind)
        assert "no invented enforcement" in text.lower()
        assert "validate_edit" in text
        assert "no GitGrit policy covers this" in text


def test_claude_flavor_points_at_plugin_skill():
    """Claude Code users get bootstrap + enforcement via the plugin's
    SessionStart hook and `policy-enforcement` skill — instructions just
    point there, they don't duplicate the workflow."""
    text = select_instructions("claude")
    assert "policy-enforcement" in text
    assert "session_bootstrap" in text


def test_generic_flavor_carries_explicit_bootstrap_and_validate_workflow():
    """Generic clients have no SessionStart hook, so the explicit bootstrap +
    per-edit validate_edit workflow has to live in the instructions."""
    text = select_instructions("generic")
    assert "session_bootstrap" in text
    assert "validate_edit" in text
    assert "introduced_violations" in text
    assert "export_setup_files" in text
