import subprocess
import sys
from unittest import TestCase

from app.domain.notifications import BODY_MAX, first_line


class FirstLineTests(TestCase):
    def test_plain_text_is_summarized_by_its_first_line(self):
        self.assertEqual(first_line("401 Bad credentials\nmore detail"), "401 Bad credentials")

    def test_a_traceback_is_summarized_by_its_exception_line(self):
        text = (
            "Standard execution error: Traceback (most recent call last):\n"
            '  File "/entrypoint.py", line 1, in <module>\n'
            "RuntimeError: boom from standard"
        )
        self.assertEqual(first_line(text), "RuntimeError: boom from standard")

    def test_blank_lines_and_padding_are_ignored(self):
        self.assertEqual(first_line("\n   \n  sandbox exploded  \n"), "sandbox exploded")

    def test_empty_or_missing_text_is_empty(self):
        self.assertEqual(first_line(""), "")
        self.assertEqual(first_line(None), "")

    def test_long_lines_are_cut(self):
        self.assertEqual(len(first_line("x" * 500)), BODY_MAX)


class PurityTests(TestCase):
    def test_import_does_not_load_django(self):
        code = (
            "import sys, app.domain.notifications;"
            "sys.exit(1 if 'django' in sys.modules else 0)"
        )
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)
