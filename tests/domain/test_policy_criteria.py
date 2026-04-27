import pytest

from app.domain.policy_criteria import language_matches, score_to_grade


class TestLanguageMatches:
    def test_empty_policy_languages_matches_every_project(self):
        assert language_matches([], ["python", "go"]) is True
        assert language_matches([], []) is True

    def test_matches_when_any_language_overlaps(self):
        assert language_matches(["python"], ["Python", "YAML"]) is True

    def test_is_case_insensitive(self):
        assert language_matches(["Python"], ["python"]) is True
        assert language_matches(["PYTHON"], ["python"]) is True

    def test_no_overlap_returns_false(self):
        assert language_matches(["rust"], ["python", "go"]) is False

    def test_empty_project_languages_with_non_empty_policy_returns_false(self):
        assert language_matches(["python"], []) is False


class TestScoreToGrade:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (None, "unknown"),
            (100, "excellent"),
            (90, "excellent"),
            (89.9, "good"),
            (70, "good"),
            (69.9, "warning"),
            (50, "warning"),
            (49.9, "critical"),
            (0, "critical"),
        ],
    )
    def test_boundaries(self, score, expected):
        assert score_to_grade(score) == expected
