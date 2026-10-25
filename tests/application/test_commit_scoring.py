"""Scoring commits as their checks finish: a check records what it expects
and each run its importance when queued; once none of its runs is going it
saves its outcome from its own runs alone (no score while an expected
standard errored or never ran in it, else failed or scored); a commit reads
its newest check; a branch reads its newest commit, whatever its outcome;
and the project reads its default branch."""
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
        assert scoring.project_score(self.project) == commit_score

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
    """A commit reads its newest check, alone."""

    def test_a_single_standard_rerun_leaves_the_others_not_run(self):
        first = self.check()
        self.result(first, self.a, score=100)
        self.result(first, self.b, Status.FAILED, 0)
        scoring.score_check(first)

        rerun = self.check(expected=[self.a, self.b])
        self.result(rerun, self.b, score=100)

        assert scoring.score_check(rerun).reason == "A not run"
        assert scoring.project_score(self.project).commit_check == rerun

    def test_a_full_rerun_turns_an_error_into_a_score(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b, Status.ERROR, 0)
        assert scoring.score_check(first).outcome == "no_score"

        rerun = self.check()
        self.result(rerun, self.a)
        self.result(rerun, self.b, score=50)

        assert scoring.score_check(rerun).value == 75
        assert scoring.commit_standing(self.project, "c1", "main").outcome == "scored"

    def test_a_rerun_that_errors_replaces_an_earlier_score(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)

        rerun = self.check()
        self.result(rerun, self.a)
        self.result(rerun, self.b, Status.ERROR, 0)
        scoring.score_check(rerun)

        assert (scoring.project_score(self.project).outcome, scoring.project_score(self.project).reason) == (
            "no_score", "B errored"
        )

    def test_a_commit_is_checking_while_a_recheck_runs_so_the_project_has_no_score_yet(self):
        first = self.check()
        self.result(first, self.a)
        self.result(first, self.b)
        scoring.score_check(first)
        recheck = self.check()
        self.result(recheck, self.a, Status.RUNNING, 0)

        standing = scoring.commit_standing(self.project, "c1", "main")

        assert (standing.outcome, standing.expected_count, standing.value) == ("checking", 2, None)
        assert scoring.project_score(self.project) is None
        assert scoring.branch_head(self.project, "main").checking

    def test_a_check_that_saved_nothing_says_what_it_gives_now(self):
        # Checks recorded before every finished check saved its outcome.
        check = self.check()
        self.result(check, self.a)

        standing = scoring.commit_standing(self.project, "c1", "main")

        assert (standing.outcome, standing.reason) == ("no_score", "B not run")

    def test_a_commit_never_checked_on_the_branch_has_no_standing(self):
        assert scoring.commit_standing(self.project, "c1", "main") is None


class ProjectScoreTests(Fixture):
    def test_the_newest_commit_on_the_default_branch(self):
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

    def test_no_checked_commit_means_no_score(self):
        assert scoring.project_score(self.project) is None
        assert scoring.branch_head(self.project, "main") is None

    def test_the_newest_commit_is_read_even_with_no_score(self):
        now = timezone.now()
        self._scored("old", 90, now - timedelta(days=1))
        newer = self.check(sha="new", committed_at=now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.ERROR, 0)
        no_score = scoring.score_check(newer)

        assert scoring.project_score(self.project) == no_score
        assert scoring.project_scores([self.project]) == {self.project.pk: no_score}

    def test_a_failed_commit_is_what_the_project_shows(self):
        check = self.check()
        self.result(check, self.a, Status.FAILED, 0, importance="required")
        self.result(check, self.b)
        scoring.score_check(check)

        assert scoring.project_score(self.project).outcome == "failed"

    def test_before_a_run_the_project_had_its_newest_score_without_it(self):
        now = timezone.now()
        before = self._scored("old", 90, now - timedelta(days=1))
        newer = self.check(sha="new", committed_at=now)
        run = self.result(newer, self.a, Status.FAILED, 0, importance="required")
        self.result(newer, self.b)
        scoring.score_check(newer)

        assert scoring.project_score(self.project, excluding=[run.pk]) == before


class BranchHeadTests(Fixture):
    """A branch reads its newest commit's newest check; many projects are
    read at once the same way."""

    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self._scored("old", 90, self.now - timedelta(days=1))

    def test_the_newest_commit_with_no_score_says_why(self):
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.ERROR, 0)
        scoring.score_check(newer)

        head = scoring.branch_head(self.project, "main")

        assert (head.sha, head.outcome, head.standing.reason, head.score.outcome) == ("new", "no_score", "B errored", "no_score")

    def test_the_newest_commit_still_checking_has_no_score_yet(self):
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        self.result(newer, self.b, Status.RUNNING, 0)

        head = scoring.branch_head(self.project, "main")

        assert (head.sha, head.outcome, head.score) == ("new", "checking", None)
        assert (head.standing.finished_count, head.standing.expected_count) == (1, 2)
        assert scoring.project_scores([self.project]) == {}

    def test_rechecking_an_older_commit_does_not_move_the_head(self):
        newest = self._scored("new", 40, self.now)
        self._scored("old", 100, self.now - timedelta(days=1))

        assert scoring.branch_head(self.project, "main").score == newest

    def test_many_projects_are_read_the_same_as_one(self):
        other = baker.make("app.Project", tenant=self.tenant, default_branch="trunk", languages=[])
        check = baker.make(
            "app.CommitCheck", project=other, branch="trunk", commit_sha="t1", event_type="push",
            expected_standard_ids=[str(self.a.pk)],
        )
        baker.make("app.StandardExecution", project=other, standard=self.a, standard_name="A",
                   commit_check=check, status=Status.RUNNING, score=0)
        newer = self.check(sha="new", committed_at=self.now)
        self.result(newer, self.a)
        self.result(newer, self.b, score=50)
        scoring.score_check(newer)

        heads = scoring.project_heads([self.project, other])

        for project in (self.project, other):
            one = scoring.branch_head(project, project.default_branch)
            assert (heads[project.pk].check, heads[project.pk].outcome, heads[project.pk].score) == (
                one.check, one.outcome, one.score
            )
        assert heads[other.pk].outcome == "checking"

    def test_a_commits_history_is_every_check_oldest_first_each_with_its_outcome(self):
        first = self.check(sha="new", committed_at=self.now)
        self.result(first, self.a)
        self.result(first, self.b, Status.ERROR, 0)
        scoring.score_check(first)
        second = self.check(sha="new", committed_at=self.now)
        self.result(second, self.a)
        self.result(second, self.b)
        scoring.score_check(second)

        runs = scoring.commit_history(self.project, ["new"], branch="main")["new"]

        assert [(r.check, r.outcome) for r in runs] == [(first, "no_score"), (second, "scored")]
        assert scoring.check_run(self.project, first.pk).standing.reason == "B errored"
        assert scoring.check_run(baker.make("app.Project"), first.pk) is None


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

        assert scoring.project_score(self.project).reason == "B errored"
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
