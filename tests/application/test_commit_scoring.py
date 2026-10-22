"""Scoring commits as their checks finish: a check records what it expects
and each run its importance when queued; once none of its runs is going it
saves the commit's outcome (no score while an expected standard errored or
never ran, else failed or scored); a commit reads its newest; and the
project's score is the newest verdict (failed or scored) on its default
branch, which a newer commit with no score never hides."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application import scoring
from app.application.standard_runs import enqueue_run
from app.domain.models import CommitCheck, CommitScore, StandardExecution
from tests.support import defer_patch

Status = StandardExecution.Status


class Fixture(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make(
            "app.Project", tenant=self.tenant, default_branch="main", languages=[]
        )
        self.a = self._attach("A")
        self.b = self._attach("B")

    def _attach(self, name, importance="major"):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, name=name, enabled=True, draft=False, criteria={}
        )
        self.project.standards.add(standard)
        self.project.project_standards.filter(standard=standard).update(importance=importance)
        return standard

    def check(self, sha="c1", branch="main", expected=None, committed_at=None):
        return baker.make(
            "app.CommitCheck",
            project=self.project,
            branch=branch,
            commit_sha=sha,
            committed_at=committed_at,
            event_type="push",
            expected_standard_ids=[str(s.pk) for s in (expected or [self.a, self.b])],
        )

    def result(self, check, standard, status=Status.PASSED, score=100, importance="major"):
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            commit_check=check,
            status=status,
            score=score,
            importance=importance,
        )


    def _scored(self, sha, value, committed_at, branch="main"):
        check = self.check(sha=sha, branch=branch, committed_at=committed_at)
        self.result(check, self.a, score=value)
        self.result(check, self.b, score=value)
        return scoring.score_check(check)


class ScoreCheckTests(Fixture):
    def test_a_complete_commit_gets_a_score(self):
        check = self.check()
        self.result(check, self.a, score=100)
        self.result(check, self.b, Status.FAILED, 50)

        commit_score = scoring.score_check(check)

        assert (commit_score.value, commit_score.failed) == (75, False)
        assert commit_score.executions.count() == 2

    def test_a_commit_an_expected_standard_never_ran_on_has_no_score_and_says_which(self):
        check = self.check()
        self.result(check, self.a)

        commit_score = scoring.score_check(check)

        assert (commit_score.outcome, commit_score.value, commit_score.reason) == ("no_score", None, "B not run")
        assert scoring.project_score(self.project) is None

    def test_an_errored_standard_of_any_importance_leaves_no_score(self):
        check = self.check()
        self.result(check, self.a)
        self.result(check, self.b, Status.ERROR, 0, importance="minor")

        commit_score = scoring.score_check(check)

        assert (commit_score.outcome, commit_score.reason) == ("no_score", "B errored")
        assert commit_score.executions.count() == 2

    def test_a_failed_required_standard_with_another_errored_is_no_score_not_failed(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 0, importance="required")
        self.result(check, self.b, Status.ERROR, 0)

        commit_score = scoring.score_check(check)

        assert (commit_score.outcome, commit_score.failed, commit_score.reason) == ("no_score", False, "B errored")

    def test_a_failed_required_standard_with_another_never_run_is_no_score_not_failed(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 0, importance="required")

        assert scoring.score_check(check).reason == "B not run"

    def test_an_expected_standard_deleted_since_is_named_as_removed(self):
        check = self.check()
        self.result(check, self.a)
        self.b.delete()

        assert scoring.score_check(check).reason == "a removed standard not run"

    def test_a_check_still_running_is_not_scored(self):
        check = self.check()
        self.result(check, self.a)
        self.result(check, self.b, Status.RUNNING, 0)

        assert scoring.score_check(check) is None
        assert not CommitScore.objects.exists()

    def test_a_check_with_no_commit_yet_is_not_scored(self):
        check = self.check(sha="")
        self.result(check, self.a)
        self.result(check, self.b)

        assert scoring.score_check(check) is None

    def test_a_failing_required_result_fails_it_with_the_reason_and_no_value(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 80, importance="required")
        self.result(check, self.b)

        commit_score = scoring.score_check(check)

        assert (commit_score.value, commit_score.failed, commit_score.reason) == (None, True, "A failing")
        assert commit_score.outcome == "failed"

    def test_weights_come_from_the_importance_at_run_time(self):
        check = self.check()
        self.result(check, self.a, score=90)
        self.result(check, self.b, Status.FAILED, 30, importance="minor")
        # Changed after the run: no effect on this commit.
        self.project.project_standards.update(importance="required")

        assert scoring.score_check(check).value == 70


class RecheckTests(Fixture):
    def test_a_single_standard_rerun_rescores_with_the_newest_result(self):
        first = self.check()
        self.result(first, self.a, score=100)
        self.result(first, self.b, Status.FAILED, 0)
        scoring.score_check(first)

        rerun = self.check(expected=[self.a, self.b])
        self.result(rerun, self.b, score=100)

        assert scoring.score_check(rerun).value == 100

    def test_a_recheck_that_ends_without_every_standard_keeps_the_project_score(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)
        c = self._attach("C")

        recheck = self.check(expected=[self.a, self.b, c])
        self.result(recheck, self.a)

        # B's result from the first check still counts: only C never ran.
        assert scoring.score_check(recheck).reason == "C not run"
        assert scoring.project_score(self.project).commit_check == first
        standing = scoring.commit_standing(self.project, "c1", "main")
        assert (standing.outcome, standing.reason) == ("no_score", "C not run")
        assert (standing.finished_count, standing.expected_count) == (2, 3)

    def test_a_commit_is_checking_while_a_recheck_runs_and_keeps_its_verdict_on_the_project(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)
        recheck = self.check()
        self.result(recheck, self.a, Status.RUNNING, 0)

        standing = scoring.commit_standing(self.project, "c1", "main")

        assert (standing.outcome, standing.expected_count, standing.value) == ("checking", 2, None)
        assert scoring.project_score(self.project).commit_check == first

    def test_a_rerun_that_passes_turns_an_error_into_a_score(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b, Status.ERROR, 0)
        assert scoring.score_check(first).outcome == "no_score"

        rerun = self.check()
        self.result(rerun, self.b, score=50)

        assert scoring.score_check(rerun).value == 75
        assert scoring.commit_standing(self.project, "c1", "main").outcome == "scored"

    def test_a_check_that_saved_nothing_says_what_it_gives_now(self):
        # Checks recorded before every finished check saved its outcome.
        check = self.check()
        self.result(check, self.a)

        standing = scoring.commit_standing(self.project, "c1", "main")

        assert (standing.outcome, standing.reason) == ("no_score", "B not run")

    def test_a_commit_never_checked_on_the_branch_has_no_standing(self):
        assert scoring.commit_standing(self.project, "c1", "main") is None


class ProjectScoreTests(Fixture):
    def test_the_newest_scored_commit_on_the_default_branch(self):
        now = timezone.now()
        self._scored("old", 40, now - timedelta(days=2))
        newest = self._scored("new", 90, now - timedelta(days=1))
        self._scored("feature", 10, now, branch="feature")

        assert scoring.project_score(self.project) == newest

    def test_checking_an_old_commit_again_does_not_replace_a_newer_one(self):
        now = timezone.now()
        newest = self._scored("new", 90, now)
        self._scored("old", 40, now - timedelta(days=5))

        assert scoring.project_score(self.project) == newest

    def test_no_scored_commit_means_no_score(self):
        assert scoring.project_score(self.project) is None

    def test_a_newer_commit_with_no_score_never_hides_the_last_verdict(self):
        now = timezone.now()
        verdict = self._scored("old", 90, now - timedelta(days=1))
        newer = self.check(sha="new", committed_at=now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.ERROR, 0)
        scoring.score_check(newer)

        assert scoring.project_score(self.project) == verdict
        assert scoring.project_scores([self.project]) == {self.project.pk: verdict}

    def test_a_failed_commit_is_a_verdict_the_project_shows(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 0, importance="required")
        self.result(check, self.b)
        scoring.score_check(check)

        assert scoring.project_score(self.project).outcome == "failed"


class NewerCommitTests(Fixture):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.verdict = self._scored("old", 90, self.now - timedelta(days=1))

    def test_a_newer_commit_with_no_score_says_why(self):
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.ERROR, 0)
        scoring.score_check(newer)

        found = scoring.newer_commit(self.project, "main", self.verdict)

        assert (found.sha, found.standing.outcome, found.standing.reason) == ("new", "no_score", "B errored")

    def test_a_newer_commit_still_checking(self):
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.RUNNING, 0)

        found = scoring.newer_commit(self.project, "main", self.verdict)

        assert (found.standing.outcome, found.standing.finished_count, found.standing.expected_count) == ("checking", 1, 2)

    def test_none_when_the_newest_commit_is_the_verdict(self):
        assert scoring.newer_commit(self.project, "main", self.verdict) is None

    def test_none_when_the_newest_commit_has_a_verdict_of_its_own(self):
        newest = self._scored("new", 40, self.now)

        assert scoring.newer_commit(self.project, "main", self.verdict) is None
        assert scoring.newer_commit(self.project, "main", newest) is None

    def test_a_newer_commit_with_no_score_when_there_is_no_verdict_at_all(self):
        CommitScore.objects.all().delete()
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        scoring.score_check(newer)

        assert scoring.newer_commit(self.project, "main", None).standing.reason == "B not run"


class EnqueueRecordsSnapshotsTests(Fixture):
    def test_a_check_expects_the_standards_that_apply_and_runs_keep_their_importance(self):
        self.project.project_standards.filter(standard=self.b).update(importance="minor")
        draft = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=True, criteria={})
        self.project.standards.add(draft)

        with defer_patch():
            summary = enqueue_run(self.project, [self.b], commit_sha="c9")

        check = CommitCheck.objects.get(commit_sha="c9")
        assert set(check.expected_standard_ids) == {str(self.a.pk), str(self.b.pk)}
        execution = StandardExecution.objects.get(pk=summary["executions"][0]["execution_id"])
        assert execution.importance == "minor"

    def test_a_webhook_check_expects_the_standards_its_event_matched(self):
        with defer_patch():
            enqueue_run(self.project, [self.a], commit_sha="c8", skip_running=False, expected=[self.a])

        assert CommitCheck.objects.get(commit_sha="c8").expected_standard_ids == [str(self.a.pk)]


class StaleRunsTests(Fixture):
    def test_a_required_run_stuck_running_errors_and_leaves_no_score(self):
        from app.application.standard_runs import expire_stale_runs

        check = self.check()
        self.result(check, self.a)
        stuck = self.result(check, self.b, Status.RUNNING, 0, importance="required")
        StandardExecution.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(days=1))

        expire_stale_runs()

        assert scoring.project_score(self.project) is None
        standing = scoring.commit_standing(self.project, "c1", "main")
        assert (standing.outcome, standing.reason) == ("no_score", "B errored")


class DetachedStandardDropsOffTests(Fixture):
    def test_a_recheck_without_a_detached_standard_drops_it_from_the_commit(self):
        from app.application.commit_checks import commit_results

        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b, Status.ERROR, 0)
        scoring.score_check(first)
        self.project.standards.remove(self.b)

        recheck = self.check(expected=[self.a])
        self.result(recheck, self.a, score=80)
        scoring.score_check(recheck)

        row = commit_results(self.project, "c1")
        assert [r.standard_id for r in row.results] == [self.a.pk]
        assert row.score == 80


class FailedCommitHasNoValueConstraintTests(TestCase):
    """The database keeps "failed" a verdict: a failed commit score with a
    number is refused."""

    def test_a_failed_score_with_a_value_is_refused(self):
        from django.db import IntegrityError, transaction

        check = baker.make("app.CommitCheck", commit_sha="a" * 40)
        with self.assertRaises(IntegrityError), transaction.atomic():
            baker.make("app.CommitScore", project=check.project, commit_check=check, value=0, failed=True)
