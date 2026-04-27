import asyncio
from unittest.mock import MagicMock

from django.test import TestCase

from app.infrastructure.mcp import context
from app.infrastructure.mcp.setup.rule_files import (
    render,
    to_clinerules,
    to_cursor_mdc,
)
from app.infrastructure.mcp.tools.setup import export_setup_files


class TestRuleFileGenerators(TestCase):
    def test_cursor_mdc_has_alwaysapply_frontmatter(self):
        out = to_cursor_mdc()
        assert out.startswith("---\n")
        assert "alwaysApply: true" in out
        # Operational guidance must be present
        assert "session_bootstrap" in out
        assert "validate_edit" in out

    def test_clinerules_is_plain_markdown(self):
        out = to_clinerules()
        assert not out.startswith("---")
        assert "session_bootstrap" in out
        assert "validate_edit" in out

    def test_render_returns_target_paths_inside_client_convention(self):
        cursor_path, _ = render("cursor")
        cline_path, _ = render("cline")
        assert cursor_path == ".cursor/rules/gitgrit.mdc"
        assert cline_path == ".clinerules/gitgrit.md"

    def test_render_rejects_unsupported_client(self):
        import pytest
        with pytest.raises(ValueError, match="Unsupported client"):
            render("vim")  # type: ignore[arg-type]


class TestExportSetupFilesToolKindGate(TestCase):
    def _set(self, kind):
        return context.set_auth(
            context.AuthContext(
                user=MagicMock(), tenant=MagicMock(), client_kind=kind,
            )
        )

    def test_claude_token_gets_not_applicable(self):
        token = self._set("claude")
        try:
            out = asyncio.run(export_setup_files("cursor"))
        finally:
            context.reset_auth(token)
        assert out.get("error") == "not_applicable"
        assert "files" not in out

    def test_generic_token_gets_files(self):
        token = self._set("generic")
        try:
            out = asyncio.run(export_setup_files("cursor"))
        finally:
            context.reset_auth(token)
        assert "error" not in out
        assert out["files"][0]["path"] == ".cursor/rules/gitgrit.mdc"
        assert "alwaysApply" in out["files"][0]["content"]

    def test_generic_all_returns_both_clients(self):
        token = self._set("generic")
        try:
            out = asyncio.run(export_setup_files("all"))
        finally:
            context.reset_auth(token)
        paths = sorted(f["path"] for f in out["files"])
        assert paths == [".clinerules/gitgrit.md", ".cursor/rules/gitgrit.mdc"]

    def test_generic_unknown_client_is_structured_error(self):
        token = self._set("generic")
        try:
            out = asyncio.run(export_setup_files("vim"))
        finally:
            context.reset_auth(token)
        assert out.get("error") == "unsupported_client"
        assert "vim" in out["message"]
