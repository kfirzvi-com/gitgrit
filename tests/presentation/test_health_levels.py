"""Health levels derive from the grade letter, nothing else."""
from django.test import SimpleTestCase

from app.domain.health import (
    ATTENTION,
    FAILING,
    GOOD,
    UNKNOWN,
    project_level,
    stack_level,
)


class TestHealthFromLetter(SimpleTestCase):
    def test_level_from_letter(self):
        cases = {
            "A+": GOOD,
            "A": GOOD,
            "B": GOOD,
            "C": ATTENTION,
            "D": ATTENTION,
            "F": FAILING,
            "—": UNKNOWN,
            None: UNKNOWN,
        }
        for letter, expected in cases.items():
            with self.subTest(letter=letter):
                self.assertEqual(project_level(letter), expected)

    def test_stack_is_its_worst_project_and_unknown_never_wins(self):
        self.assertEqual(stack_level([GOOD, UNKNOWN, ATTENTION]), ATTENTION)
        self.assertEqual(stack_level([GOOD, FAILING]), FAILING)
        self.assertEqual(stack_level([UNKNOWN, GOOD]), GOOD)
        self.assertEqual(stack_level([]), UNKNOWN)
