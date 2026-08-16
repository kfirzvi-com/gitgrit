from django.test import SimpleTestCase

from app.infrastructure.mcp.instructions import (
    build_instructions,
    select_instructions,
)

# MCP `instructions` are injected into the system prompt and truncated by the
# client. Claude Code drops everything past ~1.9k chars; we cap at 1.9k.
_LENGTH_CAP = 1900


class InstructionsTests(SimpleTestCase):
    def test_returns_non_empty_string(self):
        result = build_instructions()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_default_flavor_is_claude(self):
        self.assertEqual(build_instructions(), select_instructions("claude"))

    def test_both_flavors_under_length_cap(self):
        """Regression guard: both flavors must fit under the client-side cap so
        nothing is silently dropped before reaching the model."""
        for kind in ("claude", "generic"):
            with self.subTest(kind=kind):
                text = select_instructions(kind)
                self.assertLessEqual(
                    len(text),
                    _LENGTH_CAP,
                    f"{kind} instructions are {len(text)} chars, "
                    f"over the {_LENGTH_CAP}-char cap.",
                )

    def test_both_flavors_have_core_concepts(self):
        for kind in ("claude", "generic"):
            with self.subTest(kind=kind):
                text = select_instructions(kind)
                self.assertIn("## Core concepts", text)
                self.assertIn("**Policy**", text)
                self.assertIn("**Project**", text)

    def test_both_flavors_carry_no_invented_enforcement_rule(self):
        """Hard guardrail: the model must never enforce a rule that didn't come
        from `validate_edit` for this project. The hooks and skills repeat this,
        but it must also live in the always-loaded MCP instructions."""
        for kind in ("claude", "generic"):
            with self.subTest(kind=kind):
                text = select_instructions(kind)
                self.assertIn("no invented enforcement", text.lower())
                self.assertIn("validate_edit", text)
                self.assertIn("no GitGrit policy covers this", text)

    def test_claude_flavor_points_at_plugin_skill(self):
        """Claude Code users get bootstrap + enforcement via the plugin's
        SessionStart hook and `policy-enforcement` skill — instructions just
        point there, they don't duplicate the workflow."""
        text = select_instructions("claude")
        self.assertIn("policy-enforcement", text)
        self.assertIn("session_bootstrap", text)

    def test_generic_flavor_carries_explicit_bootstrap_and_validate_workflow(self):
        """Generic clients have no SessionStart hook, so the explicit bootstrap +
        per-edit validate_edit workflow has to live in the instructions."""
        text = select_instructions("generic")
        self.assertIn("session_bootstrap", text)
        self.assertIn("validate_edit", text)
        self.assertIn("introduced_violations", text)
        self.assertIn("export_setup_files", text)
