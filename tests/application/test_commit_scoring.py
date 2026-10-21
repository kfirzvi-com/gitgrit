"""Scoring commits as their checks finish: a check records what it expects
and each run its importance when queued; a commit is scored only once every
expected standard has a finished result there; it keeps its last score until
a newer check completes it again; and the project's score is the newest
scored commit on its default branch."""
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


class ScoreCheckTests(Fixture):
    def test_a_complete_commit_gets_a_score(self):
        check = self.check()
        self.result(check, self.a, score=100)
        self.result(check, self.b, Status.FAILED, 50)

        commit_score = scoring.score_check(check)

        assert (commit_score.value, commit_score.failed) == (75, False)
        assert commit_score.executions.count() == 2

    def test_an_incomplete_commit_gets_none(self):
        check = self.check()
        self.result(check, self.a)

        assert scoring.score_check(check) is None
        assert not CommitScore.objects.exists()

    def test_a_check_still_running_is_not_scored(self):
        check = self.check()
        self.result(check, self.a)
        self.result(check, self.b, Status.RUNNING, 0)

        assert scoring.score_check(check) is None

    def test_a_failing_required_result_makes_it_zero_with_the_reason(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 80, importance="required")
        self.result(check, self.b)

        commit_score = scoring.score_check(check)

        assert (commit_score.value, commit_score.failed, commit_score.reason) == (0, True, "A failing")

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

    def test_a_recheck_that_ends_incomplete_keeps_the_last_score(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)
        c = self._attach("C")

        recheck = self.check(expected=[self.a, self.b, c])
        self.result(recheck, self.a)

        assert scoring.score_check(recheck) is None
        assert scoring.project_score(self.project).commit_check == first
        assert scoring.commit_state(self.project, "c1", "main").state == scoring.INCOMPLETE

    def test_the_state_says_in_progress_while_a_recheck_runs(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)
        recheck = self.check()
        self.result(recheck, self.a, Status.RUNNING, 0)

        state = scoring.commit_state(self.project, "c1", "main")

        assert (state.state, state.expected_count) == (scoring.IN_PROGRESS, 2)


class ProjectScoreTests(Fixture):
    def _scored(self, sha, value, committed_at, branch="main"):
        check = self.check(sha=sha, branch=branch, committed_at=committed_at)
        self.result(check, self.a, score=value)
        self.result(check, self.b, score=value)
        return scoring.score_check(check)

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
    def test_a_required_run_that_never_finished_fails_the_commit(self):
        from app.application.standard_runs import expire_stale_runs

        check = self.check()
        self.result(check, self.a)
        stuck = self.result(check, self.b, Status.RUNNING, 0, importance="required")
        StandardExecution.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(days=1))

        expire_stale_runs()

        commit_score = scoring.project_score(self.project)
        assert (commit_score.value, commit_score.failed, commit_score.reason) == (0, True, "could not verify B")
