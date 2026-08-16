from django.test import SimpleTestCase

from app.domain.policy_criteria import language_matches, score_to_grade


class TestLanguageMatches(SimpleTestCase):
    def test_empty_policy_languages_matches_every_project(self):
        self.assertIs(language_matches([], ["python", "go"]), True)
        self.assertIs(language_matches([], []), True)

    def test_matches_when_any_language_overlaps(self):
        self.assertIs(language_matches(["python"], ["Python", "YAML"]), True)

    def test_is_case_insensitive(self):
        self.assertIs(language_matches(["Python"], ["python"]), True)
        self.assertIs(language_matches(["PYTHON"], ["python"]), True)

    def test_no_overlap_returns_false(self):
        self.assertIs(language_matches(["rust"], ["python", "go"]), False)

    def test_empty_project_languages_with_non_empty_policy_returns_false(self):
        self.assertIs(language_matches(["python"], []), False)


class TestScoreToGrade(SimpleTestCase):
    def test_boundaries(self):
        cases = [
            (None, "unknown"),
            (100, "excellent"),
            (90, "excellent"),
            (89.9, "good"),
            (70, "good"),
            (69.9, "warning"),
            (50, "warning"),
            (49.9, "critical"),
            (0, "critical"),
        ]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(score_to_grade(score), expected)
