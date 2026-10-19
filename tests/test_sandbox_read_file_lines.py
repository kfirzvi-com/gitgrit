"""Models read large or minified files in pages of short, numbered lines
(sandbox ProjectContext.read_file_lines)."""
import sys
from pathlib import Path

from django.test import SimpleTestCase

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from project_context import MAX_READ_CHARS, ProjectContext, break_long_lines  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

MINIFIED = "".join(f"var a{i}=function(x){{return x+{i}}};" for i in range(4000))  # ~130 KB, one line


class BreakLongLinesTests(SimpleTestCase):
    def test_short_lines_are_kept(self):
        self.assertEqual(break_long_lines("a\nb", width=10), ["a", "b"])

    def test_a_long_line_breaks_after_code_punctuation(self):
        pieces = break_long_lines("aaaa;bbbb;cccc;dddd", width=10)
        self.assertEqual(pieces, ["aaaa;bbbb;", "cccc;dddd"])
        self.assertTrue(all(len(p) <= 10 for p in pieces))

    def test_no_punctuation_breaks_at_the_width(self):
        self.assertEqual(break_long_lines("x" * 25, width=10), ["x" * 10, "x" * 10, "x" * 5])

    def test_nothing_is_lost(self):
        self.assertEqual("".join(break_long_lines(MINIFIED)), MINIFIED)


class ReadFileLinesTests(SimpleTestCase):
    def setUp(self):
        self.project = ProjectContext(MockProvider("p", data={"get_file_content": {"app.js": MINIFIED}}))

    def test_a_minified_bundle_reads_as_many_short_lines(self):
        page = self.project.read_file_lines("app.js")
        self.assertGreater(page["total_lines"], 500)
        self.assertTrue(page["lines"][0].startswith("1: var a0="))
        self.assertLessEqual(sum(len(line) for line in page["lines"]), MAX_READ_CHARS)

    def test_pages_continue_where_the_last_one_stopped(self):
        first = self.project.read_file_lines("app.js", count=10)
        second = self.project.read_file_lines("app.js", start=first["next_start"], count=10)
        self.assertEqual(first["next_start"], 11)
        self.assertTrue(second["lines"][0].startswith("11: "))

    def test_the_last_page_has_no_next(self):
        total = self.project.read_file_lines("app.js")["total_lines"]
        last = self.project.read_file_lines("app.js", start=total)
        self.assertIsNone(last["next_start"])
        self.assertEqual(len(last["lines"]), 1)

    def test_a_missing_file_is_none(self):
        self.assertIsNone(self.project.read_file_lines("nope.js"))
