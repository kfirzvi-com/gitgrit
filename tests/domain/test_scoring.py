"""The project score's domain: which standards a commit check expects, which
standard runs a commit is scored from, the commit's one outcome (decided in
order: checking while a run goes; no score while an expected standard errored
or never ran, Required too; failed when every standard ran and a Required one
failed; otherwise the importance-weighted average, Required and Major
counting 2 and Minor 1), where a commit stands, and how a branch's commits
are ordered."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.domain.importance import Importance
from app.domain.scoring import (
    COMMIT_SCORING_POLICY,
    AttachedStandard,
    BranchCommitTimeline,
    CommitScoreOutcome,
    CommitScoreValue,
    CommitStanding,
    ExpectedStandards,
    ScorableCommitCheck,
    StandardRunResult,
    StandardRunResultsOnCommit,
    StandardRunStatus,
)

REQUIRED, MAJOR, MINOR = Importance.REQUIRED, Importance.MAJOR, Importance.MINOR
PASSED, FAILED, ERROR, RUNNING, SKIPPED = (
    StandardRunStatus.PASSED,
    StandardRunStatus.FAILED,
    StandardRunStatus.ERROR,
    StandardRunStatus.RUNNING,
    StandardRunStatus.SKIPPED,
)
CHECKING, NO_SCORE, OUTCOME_FAILED, SCORED = (
    CommitScoreOutcome.CHECKING,
    CommitScoreOutcome.NO_SCORE,
    CommitScoreOutcome.FAILED,
    CommitScoreOutcome.SCORED,
)
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
score_commit = COMMIT_SCORING_POLICY.score_commit


def run(name, status=PASSED, standard_score=100, importance=MAJOR):
    return StandardRunResult(
        standard_id=name, standard_name=name, status=status,
        standard_score=standard_score, importance=importance,
    )


class WeightedAverageTests(SimpleTestCase):
    """Rule 3: every standard ran and no Required one failed."""

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

    def test_every_standard_failing_with_none_required_is_a_score_of_0_not_failed(self):
        value = score_commit([run("a", FAILED, 0), run("b", FAILED, 0, MINOR)])

        assert value == CommitScoreValue(0)
        assert value.outcome is SCORED

    def test_a_single_standard_is_its_own_score(self):
        assert score_commit([run("a", standard_score=42, importance=MINOR)]).value == 42

    def test_runs_that_did_not_finish_never_count(self):
        assert score_commit([run("a", standard_score=60), run("b", RUNNING, 0), run("c", SKIPPED, 0)]) == CommitScoreValue(60)

    def test_nothing_at_all_has_no_score_and_no_reason(self):
        assert score_commit([]) == CommitScoreValue(None)


class NoScoreTests(SimpleTestCase):
    """Rule 1: an expected standard without a result (errored or never
    ran), of any importance, means no score; it is checked first."""

    def test_an_errored_minor_standard_leaves_the_commit_without_a_score(self):
        value = score_commit([run("a"), run("Changelog", ERROR, 0, MINOR)])

        assert value == CommitScoreValue(None, reason="Changelog errored")
        assert value.outcome is NO_SCORE

    def test_an_errored_required_standard_is_no_score_not_failed(self):
        value = score_commit([run("No secrets", ERROR, 0, REQUIRED), run("b")])

        assert value == CommitScoreValue(None, reason="No secrets errored")
        assert not value.failed_by_required_standard

    def test_a_standard_that_never_ran_leaves_the_commit_without_a_score(self):
        value = score_commit([run("a")], not_run=["Lint"])

        assert value == CommitScoreValue(None, reason="Lint not run")

    def test_the_reason_names_every_errored_standard_then_every_one_not_run(self):
        value = score_commit([run("a", ERROR, 0), run("b"), run("c", ERROR, 0, MINOR)], not_run=["d", "e"])

        assert value.reason == "a errored, c errored, d not run, e not run"

    def test_a_failed_required_standard_with_another_errored_is_no_score_not_failed(self):
        value = score_commit([run("No secrets", FAILED, 0, REQUIRED), run("Changelog", ERROR, 0, MINOR)])

        assert value == CommitScoreValue(None, reason="Changelog errored")

    def test_a_failed_required_standard_with_another_not_run_is_no_score_not_failed(self):
        value = score_commit([run("No secrets", FAILED, 0, REQUIRED)], not_run=["Lint"])

        assert value == CommitScoreValue(None, reason="Lint not run")

    def test_every_standard_not_run_is_no_score(self):
        assert score_commit([], not_run=["a", "b"]) == CommitScoreValue(None, reason="a not run, b not run")


class RequiredGateTests(SimpleTestCase):
    """Rule 2: every standard ran and a Required one failed."""

    def test_a_failing_required_standard_fails_the_commit_with_no_value(self):
        value = score_commit([run("No secrets", FAILED, 90, REQUIRED), run("b")])

        assert value == CommitScoreValue(None, failed_by_required_standard=True, reason="No secrets failing")
        assert value.outcome is OUTCOME_FAILED

    def test_its_own_score_does_not_matter(self):
        assert score_commit([run("a", FAILED, 100, REQUIRED)]).failed_by_required_standard

    def test_the_reason_names_every_failing_required_standard(self):
        value = score_commit(
            [run("No secrets", FAILED, 0, REQUIRED), run("License", PASSED, 100, REQUIRED), run("Pinned deps", FAILED, 0, REQUIRED)]
        )

        assert value.reason == "No secrets, Pinned deps failing"

    def test_failing_major_or_minor_never_fails_the_commit(self):
        assert not score_commit([run("a", FAILED, 0), run("b", FAILED, 0, MINOR)]).failed_by_required_standard


class StandardRunResultTests(SimpleTestCase):
    def test_only_a_required_standard_that_ran_and_failed_fails_the_commit(self):
        assert run("a", FAILED, 0, REQUIRED).fails_the_commit
        assert not run("a", ERROR, 0, REQUIRED).fails_the_commit
        assert not run("a", PASSED, 100, REQUIRED).fails_the_commit
        assert not run("a", FAILED, 0, MAJOR).fails_the_commit
        assert not run("a", FAILED, 0, MINOR).fails_the_commit

    def test_an_error_is_no_result_whatever_the_importance(self):
        assert run("a", ERROR, 0, REQUIRED).errored
        assert run("a", ERROR, 0, MINOR).errored
        assert not run("a", FAILED, 0).errored

    def test_only_a_required_failure_or_an_error_needs_attention(self):
        assert run("a", FAILED, 90, REQUIRED).needs_attention
        assert run("a", ERROR, 0, REQUIRED).needs_attention
        assert run("a", ERROR, 0, MAJOR).needs_attention
        assert run("a", ERROR, 0, MINOR).needs_attention
        assert not run("a", FAILED, 0, MAJOR).needs_attention
        assert not run("a", FAILED, 0, MINOR).needs_attention
        assert not run("a", PASSED, 10, REQUIRED).needs_attention
        assert not run("a", RUNNING, 0, REQUIRED).needs_attention

    def test_finished_means_passed_failed_or_errored(self):
        assert [s for s in StandardRunStatus if s.is_finished] == [PASSED, FAILED, ERROR]


class ExpectedStandardsTests(SimpleTestCase):
    def test_a_check_expects_the_attached_standards_that_run_on_the_commit(self):
        attached = [
            AttachedStandard("on", enabled=True, draft=False, matches_criteria=True),
            AttachedStandard("off", enabled=False, draft=False, matches_criteria=True),
            AttachedStandard("draft", enabled=True, draft=True, matches_criteria=True),
            AttachedStandard("elsewhere", enabled=True, draft=False, matches_criteria=False),
        ]

        assert ExpectedStandards.from_attached(attached).standard_ids == ("on",)

    def test_an_error_is_a_finished_result(self):
        assert ExpectedStandards(("a", "b")).without_finished_result([run("a"), run("b", ERROR, 0)]) == []

    def test_a_running_or_absent_standard_has_no_finished_result(self):
        expected = ExpectedStandards(("a", "b", "c"))
        assert expected.without_finished_result([run("a"), run("b", RUNNING, 0)]) == ["b", "c"]

    def test_runs_of_unexpected_standards_do_not_count(self):
        assert ExpectedStandards(("a",)).without_finished_result([run("z")]) == ["a"]


class StandardRunResultsOnCommitTests(SimpleTestCase):
    def test_the_newest_finished_run_per_expected_standard_wins(self):
        runs = StandardRunResultsOnCommit([run("a", RUNNING, 0), run("a", FAILED, 10), run("a"), run("z")])

        picked = runs.newest_finished_per_expected_standard(ExpectedStandards(("a",)))

        assert [(p.standard_id, p.status) for p in picked] == [("a", FAILED)]

    def test_a_rerun_that_passes_replaces_an_error(self):
        runs = StandardRunResultsOnCommit([run("a"), run("a", ERROR, 0)])

        assert [p.status for p in runs.newest_finished_per_expected_standard(ExpectedStandards(("a",)))] == [PASSED]

    def test_a_rerun_that_errors_replaces_a_pass(self):
        runs = StandardRunResultsOnCommit([run("a", ERROR, 0), run("a")])

        assert [p.status for p in runs.newest_finished_per_expected_standard(ExpectedStandards(("a",)))] == [ERROR]


def check(sha="c1", expected=("a", "b"), running=False):
    return ScorableCommitCheck(
        commit_sha=sha, expected_standards=ExpectedStandards(tuple(expected)), has_running_runs=running
    )


class NewCommitScoreTests(SimpleTestCase):
    def test_every_standard_ran_scores_the_commit_from_their_runs(self):
        new_score = check().new_commit_score(StandardRunResultsOnCommit([run("a"), run("b", FAILED, 50)]))

        assert new_score.score == CommitScoreValue(75)
        assert {r.standard_id for r in new_score.run_results} == {"a", "b"}

    def test_nothing_to_decide_without_a_commit_expectations_or_while_its_runs_go(self):
        runs = StandardRunResultsOnCommit([run("a"), run("b")])
        assert check(sha="").new_commit_score(runs) is None
        assert check(expected=()).new_commit_score(runs) is None
        assert check(running=True).new_commit_score(runs) is None

    def test_an_expected_standard_that_never_finished_is_no_score_named_by_its_name(self):
        new_score = check().new_commit_score(StandardRunResultsOnCommit([run("a")]), {"a": "Readme", "b": "Lint"})

        assert new_score.score == CommitScoreValue(None, reason="Lint not run")
        assert [r.standard_id for r in new_score.run_results] == ["a"]

    def test_a_standard_with_no_known_name_is_named_by_its_id(self):
        assert check().new_commit_score(StandardRunResultsOnCommit([run("a")])).score.reason == "b not run"

    def test_a_run_still_going_in_another_check_is_not_a_result(self):
        new_score = check().new_commit_score(StandardRunResultsOnCommit([run("b", RUNNING, 0), run("a")]))

        assert new_score.score.outcome is NO_SCORE

    def test_a_required_failure_with_a_standard_never_run_is_no_score(self):
        new_score = check().new_commit_score(StandardRunResultsOnCommit([run("a", FAILED, 0, REQUIRED)]))

        assert new_score.score == CommitScoreValue(None, reason="b not run")

    def test_a_required_failure_once_every_standard_ran_fails_the_commit(self):
        new_score = check().new_commit_score(StandardRunResultsOnCommit([run("a", FAILED, 0, REQUIRED), run("b")]))

        assert new_score.score.outcome is OUTCOME_FAILED

    def test_runs_of_standards_the_check_does_not_expect_are_left_out(self):
        new_score = check(expected=("a",)).new_commit_score(StandardRunResultsOnCommit([run("a"), run("z", ERROR, 0)]))

        assert new_score.score == CommitScoreValue(100)


class CommitStandingTests(SimpleTestCase):
    def standing(self, runs, going=False, saved=None, newest=None):
        return (newest or check()).standing(
            StandardRunResultsOnCommit(runs), any_run_going=going, saved=saved, standard_names={"b": "Lint"}
        )

    def test_checking_while_a_run_on_the_commit_goes(self):
        assert self.standing([run("a")], going=True) == CommitStanding(CHECKING, "", 2, 1)

    def test_checking_while_its_own_runs_go(self):
        assert self.standing([run("a")], newest=check(running=True)) == CommitStanding(CHECKING, "", 2, 1)

    def test_checking_even_when_an_earlier_check_already_decided_it(self):
        assert self.standing([run("a"), run("b")], going=True, saved=CommitScoreValue(90)) == CommitStanding(CHECKING, "", 2, 2)

    def test_a_saved_score_is_its_outcome_with_its_value(self):
        assert self.standing([run("a"), run("b", standard_score=80)], saved=CommitScoreValue(90)) == CommitStanding(SCORED, "", 2, 2, 90)

    def test_a_saved_failure_has_its_reason_and_no_value(self):
        saved = CommitScoreValue(None, failed_by_required_standard=True, reason="a failing")

        assert self.standing([run("a", FAILED, 0, REQUIRED), run("b")], saved=saved) == CommitStanding(OUTCOME_FAILED, "a failing", 2, 2)

    def test_a_saved_no_score_has_its_reason(self):
        saved = CommitScoreValue(None, reason="Lint not run")

        assert self.standing([run("a")], saved=saved) == CommitStanding(NO_SCORE, "Lint not run", 2, 1)

    def test_a_check_that_saved_nothing_says_what_it_gives_now(self):
        assert self.standing([run("a")]) == CommitStanding(NO_SCORE, "Lint not run", 2, 1)
        assert self.standing([run("a"), run("b")]) == CommitStanding(SCORED, "", 2, 2, 100)

    def test_an_error_counts_as_finished(self):
        assert self.standing([run("a"), run("b", ERROR, 0)]) == CommitStanding(NO_SCORE, "b errored", 2, 2)

    def test_nothing_expected_or_no_commit_has_no_standing(self):
        assert self.standing([run("a")], newest=check(expected=())) is None
        assert self.standing([run("a")], newest=check(sha="")) is None


class CommitScoreOutcomeTests(SimpleTestCase):
    def test_a_saved_score_is_failed_no_score_or_scored(self):
        assert CommitScoreOutcome.of(None, failed=True) is OUTCOME_FAILED
        assert CommitScoreOutcome.of(None, failed=False) is NO_SCORE
        assert CommitScoreOutcome.of(0, failed=False) is SCORED

    def test_only_failed_and_scored_are_verdicts(self):
        assert [o for o in CommitScoreOutcome if o.is_verdict] == [OUTCOME_FAILED, SCORED]

    def test_a_commit_is_checking_while_a_run_goes_else_its_saved_outcome(self):
        assert CommitScoreOutcome.of_commit(True, SCORED) is CHECKING
        assert CommitScoreOutcome.of_commit(True, None) is CHECKING
        assert CommitScoreOutcome.of_commit(False, NO_SCORE) is NO_SCORE
        assert CommitScoreOutcome.of_commit(False, None) is None

    def test_the_order_they_are_decided_in(self):
        assert [o.value for o in CommitScoreOutcome] == ["checking", "no_score", "failed", "scored"]


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


class ListedRunsTests(SimpleTestCase):
    def test_a_commit_lists_only_the_standards_its_newest_check_expects(self):
        expected = ExpectedStandards(("a",))
        assert expected.lists_runs_of("a")
        assert not expected.lists_runs_of("detached")

    def test_checks_from_before_expectations_list_every_run(self):
        assert ExpectedStandards(()).lists_runs_of("anything")


class DidNotRunTests(SimpleTestCase):
    def test_expected_standards_that_never_ran_on_the_commit(self):
        assert ExpectedStandards(("a", "b", "c")).without_any_run(["a"]) == ["b", "c"]


class CommitScoreValueTests(SimpleTestCase):
    """Failed is a verdict, not a number."""

    def test_a_failed_commit_cannot_carry_a_value(self):
        with self.assertRaises(ValueError):
            CommitScoreValue(0, failed_by_required_standard=True)

    def test_outcomes(self):
        assert CommitScoreValue(None, failed_by_required_standard=True).outcome is OUTCOME_FAILED
        assert CommitScoreValue(0).outcome is SCORED
        assert CommitScoreValue(None, reason="a errored").outcome is NO_SCORE
