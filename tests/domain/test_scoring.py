"""The project score rule: a failing or erroring Required standard makes a
commit 0, otherwise the score is the importance-weighted average of its
results (Required and Major count 2, Minor 1), errors of other importances
are left out, and a commit is only scored once every expected standard has
a finished result."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.domain import scoring
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


T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


class ExpectedTests(SimpleTestCase):
    def test_a_check_expects_enabled_published_standards_that_apply(self):
        candidates = [
            scoring.Candidate("on", enabled=True, draft=False, applies=True),
            scoring.Candidate("off", enabled=False, draft=False, applies=True),
            scoring.Candidate("draft", enabled=True, draft=True, applies=True),
            scoring.Candidate("elsewhere", enabled=True, draft=False, applies=False),
        ]

        assert scoring.expected(candidates) == ["on"]


class CommitResultsTests(SimpleTestCase):
    def test_the_newest_finished_result_per_expected_standard_wins(self):
        newest_first = [r("a", "running", 0), r("a", "failed", 10), r("a", value=100), r("z")]

        picked = scoring.newest_per_standard(["a"], newest_first)

        assert [(p.standard_id, p.status) for p in picked] == [("a", "failed")]


class ScoreCheckTests(SimpleTestCase):
    def check(self, sha="c1", expected=("a", "b"), running=False):
        return scoring.Check(commit_sha=sha, expected_ids=tuple(expected), running=running)

    def test_a_finished_complete_check_scores_its_commit(self):
        outcome = scoring.score_check(self.check(), [r("a"), r("b", "failed", 50)])

        assert outcome.score == Score(75)
        assert {x.standard_id for x in outcome.results} == {"a", "b"}

    def test_no_score_without_a_commit_expectations_or_while_running(self):
        results = [r("a"), r("b")]
        assert scoring.score_check(self.check(sha=""), results) is None
        assert scoring.score_check(self.check(expected=()), results) is None
        assert scoring.score_check(self.check(running=True), results) is None

    def test_no_score_while_an_expected_standard_never_finished(self):
        assert scoring.score_check(self.check(), [r("a")]) is None


class OrderingTests(SimpleTestCase):
    def test_a_commit_counts_from_its_commit_time_else_its_first_check(self):
        assert scoring.ordered_at(T0, T0 + timedelta(days=3)) == T0
        assert scoring.ordered_at(None, T0) == T0

    def test_the_newest_commit_is_by_commit_time_not_by_check_time(self):
        old_rechecked = SimpleNamespace(commit_sha="old", committed_at=T0, created_at=T0 + timedelta(days=5))
        new = SimpleNamespace(commit_sha="new", committed_at=T0 + timedelta(days=1), created_at=T0 + timedelta(days=1))

        assert scoring.newest_commit([old_rechecked, new]) is new

    def test_a_commit_keeps_its_last_score(self):
        newest_first = [SimpleNamespace(commit_sha="c1", v=2), SimpleNamespace(commit_sha="c1", v=1)]

        assert scoring.latest_per_commit(newest_first)["c1"].v == 2


class CommitStateTests(SimpleTestCase):
    newest = scoring.Check(commit_sha="c1", expected_ids=("a", "b"), running=False)

    def test_in_progress_while_a_run_goes(self):
        state = scoring.commit_state(self.newest, [r("a")], running=True, scored=False)
        assert state == scoring.CommitState(scoring.IN_PROGRESS, 2, 1)

    def test_complete_when_its_newest_check_scored_it(self):
        state = scoring.commit_state(self.newest, [r("a"), r("b")], running=False, scored=True)
        assert state == scoring.CommitState(scoring.COMPLETE, 2, 2)

    def test_incomplete_when_it_finished_without_every_standard(self):
        state = scoring.commit_state(self.newest, [r("a")], running=False, scored=False)
        assert state == scoring.CommitState(scoring.INCOMPLETE, 2, 1)

    def test_nothing_expected_has_no_state(self):
        empty = scoring.Check(commit_sha="c1", expected_ids=(), running=False)
        assert scoring.commit_state(empty, [], running=False, scored=False) is None


class CommitBranchTests(SimpleTestCase):
    def test_a_commit_is_read_on_its_score_branch_else_its_last_checked_branch(self):
        assert scoring.commit_branch("main", ["feature"], "main") == "main"
        assert scoring.commit_branch(None, ["feature", "main"], "main") == "feature"
        assert scoring.commit_branch(None, [], "main") == "main"
