"""The project score rule: a failing or erroring Required standard makes a
commit 0, otherwise the score is the importance-weighted average of its
results (Required and Major count 2, Minor 1), errors of other importances
are left out, and a commit is only scored once every expected standard has
a finished result."""
from django.test import SimpleTestCase

from app.domain.importance import Importance
from app.domain.scoring import Result, Score, missing, score

REQUIRED, MAJOR, MINOR = Importance.REQUIRED, Importance.MAJOR, Importance.MINOR


def r(name, status="passed", value=100, importance=MAJOR):
    return Result(standard_id=name, name=name, status=status, score=value, importance=importance)


class WeightedAverageTests(SimpleTestCase):
    def test_equal_importance_is_the_plain_average(self):
        assert score([r("a", value=100), r("b", "failed", 50)]) == Score(75)

    def test_major_counts_twice_as_much_as_minor(self):
        # (90*2 + 30*1) / 3 = 70
        assert score([r("a", value=90), r("b", "failed", 30, MINOR)]).value == 70

    def test_a_passing_required_standard_counts_like_major(self):
        # (100*2 + 40*2) / 4 = 70
        assert score([r("a", value=100, importance=REQUIRED), r("b", "failed", 40)]).value == 70

    def test_rounds_to_a_whole_number(self):
        # (100*2 + 0*1) / 3 = 66.7
        assert score([r("a"), r("b", "failed", 0, MINOR)]).value == 67

    def test_errors_of_major_and_minor_are_left_out(self):
        assert score([r("a", value=80), r("b", "error", 0), r("c", "error", 0, MINOR)]) == Score(80)

    def test_nothing_to_average_has_no_value(self):
        assert score([r("a", "error", 0)]) == Score(None)

    def test_running_rows_never_count(self):
        assert score([r("a", value=60), r("b", "running", 0)]) == Score(60)


class RequiredGateTests(SimpleTestCase):
    def test_a_failing_required_standard_makes_the_commit_zero(self):
        result = score([r("No secrets", "failed", 90, REQUIRED), r("b", value=100)])

        assert result == Score(0, failed=True, reason="No secrets failing")

    def test_an_erroring_required_standard_fails_it_too(self):
        result = score([r("No secrets", "error", 0, REQUIRED), r("b")])

        assert result == Score(0, failed=True, reason="could not verify No secrets")

    def test_the_reason_names_every_failing_required_standard(self):
        result = score(
            [
                r("No secrets", "failed", 0, REQUIRED),
                r("License", "error", 0, REQUIRED),
                r("Pinned deps", "failed", 0, REQUIRED),
            ]
        )

        assert result.reason == "No secrets, Pinned deps failing; could not verify License"

    def test_failing_major_or_minor_never_fails_the_commit(self):
        assert not score([r("a", "failed", 0), r("b", "failed", 0, MINOR)]).failed


class CompletenessTests(SimpleTestCase):
    def test_complete_when_every_expected_standard_finished(self):
        assert missing(["a", "b"], [r("a"), r("b", "error", 0)]) == []

    def test_a_running_or_absent_standard_is_missing(self):
        assert missing(["a", "b", "c"], [r("a"), r("b", "running", 0)]) == ["b", "c"]

    def test_results_of_unexpected_standards_do_not_complete_it(self):
        assert missing(["a"], [r("z")]) == ["a"]
