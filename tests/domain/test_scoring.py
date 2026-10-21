"""The project score's domain: which standards a commit check expects, which
standard runs a commit is scored from, the commit scoring policy (a failing or
erroring Required standard makes a commit 0, otherwise the importance-weighted
average with Required and Major counting 2 and Minor 1, errored runs of other
importances left out), when a commit check scores its commit, where a commit
stands, and how a branch's commits are ordered."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.domain.importance import Importance
from app.domain.scoring import (
    COMMIT_SCORING_POLICY,
    AttachedStandard,
    BranchCommitTimeline,
    CommitScoreValue,
    CommitScoringState,
    ExpectedStandards,
    ScorableCommitCheck,
    StandardRunResult,
    StandardRunResultsOnCommit,
    StandardRunStatus,
)

REQUIRED, MAJOR, MINOR = Importance.REQUIRED, Importance.MAJOR, Importance.MINOR
PASSED, FAILED, ERROR, RUNNING = (
    StandardRunStatus.PASSED,
    StandardRunStatus.FAILED,
    StandardRunStatus.ERROR,
    StandardRunStatus.RUNNING,
)
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
score_commit = COMMIT_SCORING_POLICY.score_commit


def run(name, status=PASSED, standard_score=100, importance=MAJOR):
    return StandardRunResult(
        standard_id=name, standard_name=name, status=status,
        standard_score=standard_score, importance=importance,
    )


class WeightedAverageTests(SimpleTestCase):
    def test_equal_importance_is_the_plain_average(self):
        assert score_commit([run("a"), run("b", FAILED, 50)]) == CommitScoreValue(75)

    def test_major_counts_twice_as_much_as_minor(self):
        # (90*2 + 30*1) / 3 = 70
        assert score_commit([run("a", standard_score=90), run("b", FAILED, 30, MINOR)]).value == 70

    def test_a_passing_required_standard_counts_like_major(self):
        # (100*2 + 40*2) / 4 = 70
        assert score_commit([run("a", importance=REQUIRED), run("b", FAILED, 40)]).value == 70

    def test_rounds_to_a_whole_number(self):
        # (100*2 + 0*1) / 3 = 66.7
        assert score_commit([run("a"), run("b", FAILED, 0, MINOR)]).value == 67

    def test_errored_runs_of_major_and_minor_are_left_out(self):
        runs = [run("a", standard_score=80), run("b", ERROR, 0), run("c", ERROR, 0, MINOR)]
        assert score_commit(runs) == CommitScoreValue(80)

    def test_nothing_to_average_has_no_value(self):
        assert score_commit([run("a", ERROR, 0)]) == CommitScoreValue(None)

    def test_running_runs_never_count(self):
        assert score_commit([run("a", standard_score=60), run("b", RUNNING, 0)]) == CommitScoreValue(60)


class RequiredGateTests(SimpleTestCase):
    def test_a_failing_required_standard_makes_the_commit_zero(self):
        value = score_commit([run("No secrets", FAILED, 90, REQUIRED), run("b")])

        assert value == CommitScoreValue(0, failed_by_required_standard=True, failure_reason="No secrets failing")

    def test_an_erroring_required_standard_fails_it_too(self):
        value = score_commit([run("No secrets", ERROR, 0, REQUIRED), run("b")])

        assert value.failure_reason == "could not verify No secrets"
        assert value.failed_by_required_standard

    def test_the_reason_names_every_failing_required_standard(self):
        value = score_commit(
            [
                run("No secrets", FAILED, 0, REQUIRED),
                run("License", ERROR, 0, REQUIRED),
                run("Pinned deps", FAILED, 0, REQUIRED),
            ]
        )

        assert value.failure_reason == "No secrets, Pinned deps failing; could not verify License"

    def test_failing_major_or_minor_never_fails_the_commit(self):
        assert not score_commit([run("a", FAILED, 0), run("b", FAILED, 0, MINOR)]).failed_by_required_standard


class ExpectedStandardsTests(SimpleTestCase):
    def test_a_check_expects_the_attached_standards_that_run_on_the_commit(self):
        attached = [
            AttachedStandard("on", enabled=True, draft=False, matches_criteria=True),
            AttachedStandard("off", enabled=False, draft=False, matches_criteria=True),
            AttachedStandard("draft", enabled=True, draft=True, matches_criteria=True),
            AttachedStandard("elsewhere", enabled=True, draft=False, matches_criteria=False),
        ]

        assert ExpectedStandards.from_attached(attached).standard_ids == ("on",)

    def test_complete_when_every_expected_standard_finished(self):
        assert ExpectedStandards(("a", "b")).without_finished_result([run("a"), run("b", ERROR, 0)]) == []

    def test_a_running_or_absent_standard_has_no_finished_result(self):
        expected = ExpectedStandards(("a", "b", "c"))
        assert expected.without_finished_result([run("a"), run("b", RUNNING, 0)]) == ["b", "c"]

    def test_runs_of_unexpected_standards_do_not_complete_it(self):
        assert ExpectedStandards(("a",)).without_finished_result([run("z")]) == ["a"]


class StandardRunResultsOnCommitTests(SimpleTestCase):
    def test_the_newest_finished_run_per_expected_standard_wins(self):
        runs = StandardRunResultsOnCommit([run("a", RUNNING, 0), run("a", FAILED, 10), run("a"), run("z")])

        picked = runs.newest_finished_per_expected_standard(ExpectedStandards(("a",)))

        assert [(p.standard_id, p.status) for p in picked] == [("a", FAILED)]


class NewCommitScoreTests(SimpleTestCase):
    def check(self, sha="c1", expected=("a", "b"), running=False):
        return ScorableCommitCheck(
            commit_sha=sha, expected_standards=ExpectedStandards(tuple(expected)), has_running_runs=running
        )

    def test_a_finished_complete_check_scores_its_commit(self):
        new_score = self.check().new_commit_score(StandardRunResultsOnCommit([run("a"), run("b", FAILED, 50)]))

        assert new_score.score == CommitScoreValue(75)
        assert {r.standard_id for r in new_score.run_results} == {"a", "b"}

    def test_no_score_without_a_commit_expectations_or_while_running(self):
        runs = StandardRunResultsOnCommit([run("a"), run("b")])
        assert self.check(sha="").new_commit_score(runs) is None
        assert self.check(expected=()).new_commit_score(runs) is None
        assert self.check(running=True).new_commit_score(runs) is None

    def test_no_score_while_an_expected_standard_never_finished(self):
        assert self.check().new_commit_score(StandardRunResultsOnCommit([run("a")])) is None


class CommitScoringStateTests(SimpleTestCase):
    newest = ScorableCommitCheck(
        commit_sha="c1", expected_standards=ExpectedStandards(("a", "b")), has_running_runs=False
    )

    def state(self, runs, going, scored):
        return self.newest.commit_scoring_state(
            StandardRunResultsOnCommit(runs), any_run_going=going, scored_by_this_check=scored
        )

    def test_in_progress_while_a_run_goes(self):
        assert self.state([run("a")], True, False) == CommitScoringState(CommitScoringState.IN_PROGRESS, 2, 1)

    def test_complete_when_its_newest_check_scored_it(self):
        assert self.state([run("a"), run("b")], False, True) == CommitScoringState(CommitScoringState.COMPLETE, 2, 2)

    def test_incomplete_when_it_finished_without_every_standard(self):
        assert self.state([run("a")], False, False) == CommitScoringState(CommitScoringState.INCOMPLETE, 2, 1)

    def test_nothing_expected_has_no_state(self):
        empty = ScorableCommitCheck(commit_sha="c1", expected_standards=ExpectedStandards(()), has_running_runs=False)
        assert empty.commit_scoring_state(
            StandardRunResultsOnCommit([]), any_run_going=False, scored_by_this_check=False
        ) is None


class BranchCommitTimelineTests(SimpleTestCase):
    def test_a_commit_counts_from_its_commit_time_else_its_first_check(self):
        assert BranchCommitTimeline.commit_ordered_at(T0, T0 + timedelta(days=3)) == T0
        assert BranchCommitTimeline.commit_ordered_at(None, T0) == T0

    def test_the_newest_commit_is_by_commit_time_not_by_check_time(self):
        old_rechecked = SimpleNamespace(commit_sha="old", committed_at=T0, created_at=T0 + timedelta(days=5))
        new = SimpleNamespace(commit_sha="new", committed_at=T0 + timedelta(days=1), created_at=T0 + timedelta(days=1))

        assert BranchCommitTimeline.newest_checked_commit([old_rechecked, new]) is new

    def test_a_commit_keeps_its_last_score(self):
        newest_first = [SimpleNamespace(commit_sha="c1", v=2), SimpleNamespace(commit_sha="c1", v=1)]

        assert BranchCommitTimeline.last_score_per_commit(newest_first)["c1"].v == 2

    def test_a_commit_is_read_on_its_score_branch_else_its_last_checked_branch(self):
        read_on = BranchCommitTimeline.branch_a_commit_is_read_on
        assert read_on("main", ["feature"], "main") == "main"
        assert read_on(None, ["feature", "main"], "main") == "feature"
        assert read_on(None, [], "main") == "main"
