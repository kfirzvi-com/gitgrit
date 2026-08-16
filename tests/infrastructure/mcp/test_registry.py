from unittest.mock import MagicMock

from django.test import SimpleTestCase

from app.infrastructure.mcp.registry import (
    _prompts,
    _tools,
    apply_all,
    apply_all_prompts,
    register,
    register_prompt,
)


class RegistryTests(SimpleTestCase):
    def test_register_returns_original_function(self):
        def _fn():
            pass

        result = register(_fn)
        self.addCleanup(_tools.remove, _fn)
        self.assertIs(result, _fn)

    def test_register_adds_to_tools_list(self):
        def _fn():
            pass

        before = len(_tools)
        register(_fn)
        self.addCleanup(_tools.remove, _fn)
        self.assertEqual(len(_tools), before + 1)
        self.assertIn(_fn, _tools)

    def test_register_prompt_returns_original_function(self):
        def _fn():
            pass

        result = register_prompt(_fn)
        self.addCleanup(_prompts.remove, _fn)
        self.assertIs(result, _fn)

    def test_register_prompt_adds_to_prompts_list(self):
        def _fn():
            pass

        before = len(_prompts)
        register_prompt(_fn)
        self.addCleanup(_prompts.remove, _fn)
        self.assertEqual(len(_prompts), before + 1)
        self.assertIn(_fn, _prompts)

    def test_apply_all_calls_mcp_tool_for_each_registered_fn(self):
        mcp = MagicMock()
        apply_all(mcp)
        self.assertEqual(mcp.tool.call_count, len(_tools))

    def test_apply_all_prompts_calls_mcp_prompt_for_each_fn(self):
        mcp = MagicMock()
        apply_all_prompts(mcp)
        self.assertEqual(mcp.prompt.call_count, len(_prompts))
