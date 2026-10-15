"""Worst-of roll-up and tones: pure rules over letters."""
from django.test import SimpleTestCase

from app.domain.grading import (
    NO_GRADE,
    TONE_ATTENTION,
    TONE_FAILING,
    TONE_GOOD,
    TONE_UNKNOWN,
    tone_for,
    worst_letter,
)


class TestWorstLetter(SimpleTestCase):
    def test_worst_wins_and_ungraded_are_ignored(self):
        self.assertEqual(worst_letter(["A+", NO_GRADE, "C", "B"]), "C")
        self.assertEqual(worst_letter(["A", "F", "A+"]), "F")
        self.assertEqual(worst_letter(["A+", "A"]), "A")

    def test_nothing_graded_is_no_grade(self):
        self.assertEqual(worst_letter([]), NO_GRADE)
        self.assertEqual(worst_letter([NO_GRADE, NO_GRADE]), NO_GRADE)


class TestToneFor(SimpleTestCase):
    def test_bands(self):
        for letter in ("A+", "A", "B"):
            self.assertEqual(tone_for(letter), TONE_GOOD)
        for letter in ("C", "D"):
            self.assertEqual(tone_for(letter), TONE_ATTENTION)
        self.assertEqual(tone_for("F"), TONE_FAILING)
        self.assertEqual(tone_for(NO_GRADE), TONE_UNKNOWN)
        self.assertEqual(tone_for(None), TONE_UNKNOWN)
