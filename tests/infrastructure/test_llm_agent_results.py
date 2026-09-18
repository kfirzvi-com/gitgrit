"""How tool results are shaped before they go back to the model."""
from django.test import SimpleTestCase

from app.infrastructure.llm_agent import MAX_TOOL_RESULT_CHARS, _truncate_for_model


class TruncateForModelTests(SimpleTestCase):
    def test_short_string_passes_through(self):
        self.assertEqual(_truncate_for_model("abc"), "abc")

    def test_long_string_is_cut_with_a_marker(self):
        out = _truncate_for_model("x" * (MAX_TOOL_RESULT_CHARS + 500))
        self.assertTrue(out.startswith("x" * MAX_TOOL_RESULT_CHARS))
        self.assertIn("[truncated 500 chars]", out)

    def test_list_results_are_joined_and_capped_like_strings(self):
        # A 10k-path tree used to be JSON-dumped in full and re-sent on every
        # later turn; lists must obey the same cap as strings.
        paths = [f"src/module{i}/file.py" for i in range(2000)]
        out = _truncate_for_model(paths)
        self.assertIsInstance(out, str)
        self.assertLessEqual(len(out), MAX_TOOL_RESULT_CHARS + 40)
        self.assertIn("[truncated", out)

    def test_short_list_is_newline_joined(self):
        self.assertEqual(_truncate_for_model(["a", "b"]), "a\nb")

    def test_non_text_values_pass_through(self):
        self.assertEqual(_truncate_for_model({"k": 1}), {"k": 1})
