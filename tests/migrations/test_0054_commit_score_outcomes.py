"""0054: a check's score comes from its own runs only, under the one-outcome
rule, and every finished check gets one."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from model_bakery import baker

from app.domain.models import CommitScore, StandardExecution

migration = import_module("app.migrations.0054_commit_score_outcomes")
Status = StandardExecution.Status


class RescoreTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project")
        self.a = baker.make("app.Standard", name="A")
        self.b = baker.make("app.Standard", name="B")

    def check(self, runs, sha="a" * 40, expected=None):
        check = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha=sha,
            expected_standard_ids=[str(s.pk) for s in (expected if expected is not None else [self.a, self.b])],
        )
        for standard, status, points in runs:
            baker.make(
                "app.StandardExecution", project=self.project, commit_check=check, standard=standard,
                standard_name=standard.name, status=status, score=points, importance="major",
            )
        return check

    def test_a_score_filled_in_from_an_earlier_check_is_no_score_now(self):
        self.check([(self.a, Status.PASSED, 100), (self.b, Status.PASSED, 100)])
        rerun = self.check([(self.b, Status.PASSED, 50)])
        saved = baker.make("app.CommitScore", project=self.project, commit_check=rerun, branch="main",
                           commit_sha="a" * 40, value=75)

        migration.rescore(apps, None)

        saved.refresh_from_db()
        assert (saved.value, saved.failed, saved.reason) == (None, False, "A not run")
        assert [e.standard_name for e in saved.executions.all()] == ["B"]

    def test_a_finished_check_that_saved_nothing_gets_its_score(self):
        check = self.check([(self.a, Status.PASSED, 100), (self.b, Status.FAILED, 50)])

        migration.rescore(apps, None)

        score = CommitScore.objects.get(commit_check=check)
        assert (score.value, score.failed, score.reason, score.branch) == (75, False, "", "main")
        assert score.executions.count() == 2

    def test_a_check_still_running_or_expecting_nothing_is_left_alone(self):
        self.check([(self.a, Status.RUNNING, 0), (self.b, Status.PASSED, 100)])
        self.check([(self.a, Status.PASSED, 100)], sha="b" * 40, expected=[])

        migration.rescore(apps, None)

        assert not CommitScore.objects.exists()

    def test_a_standard_deleted_since_is_named_as_removed(self):
        gone = baker.make("app.Standard", name="Gone")
        check = self.check([(self.a, Status.PASSED, 100)], expected=[self.a, gone])
        gone_id = gone.pk
        type(gone)._base_manager.filter(pk=gone_id).delete()

        migration.rescore(apps, None)

        assert CommitScore.objects.get(commit_check=check).reason == "a removed standard not run"

    def test_an_errored_required_standard_is_no_score_before_a_failed_one_fails_it(self):
        check = self.check([(self.a, Status.FAILED, 0), (self.b, Status.ERROR, 0)])
        StandardExecution.objects.filter(commit_check=check).update(importance="required")

        migration.rescore(apps, None)

        score = CommitScore.objects.get(commit_check=check)
        assert (score.value, score.failed, score.reason) == (None, False, "B errored")

    def test_a_failed_required_standard_fails_it_with_no_value(self):
        check = self.check([(self.a, Status.FAILED, 90), (self.b, Status.PASSED, 100)])
        StandardExecution.objects.filter(commit_check=check, standard=self.a).update(importance="required")

        migration.rescore(apps, None)

        score = CommitScore.objects.get(commit_check=check)
        assert (score.value, score.failed, score.reason) == (None, True, "A failing")

    def test_the_frozen_rule_matches_the_domain_rule(self):
        from app.domain.importance import Importance
        from app.domain.scoring import COMMIT_SCORING_POLICY, StandardRunResult, StandardRunStatus

        cases = [
            ([("a", "passed", 90, "major"), ("b", "failed", 30, "minor")], []),
            ([("a", "failed", 0, "required"), ("b", "passed", 100, "major")], []),
            ([("a", "failed", 0, "required"), ("b", "error", 0, "minor")], []),
            ([("a", "failed", 0, "required")], ["c"]),
            ([("a", "error", 0, "required")], ["c", "d"]),
            ([("a", "failed", 0, "major"), ("b", "failed", 0, "minor")], []),
        ]
        for runs, not_run in cases:
            with self.subTest(runs=runs, not_run=not_run):
                frozen = migration.decide(
                    [StandardExecution(standard_name=n, status=s, score=p, importance=i) for n, s, p, i in runs], not_run
                )
                domain = COMMIT_SCORING_POLICY.score_commit(
                    [StandardRunResult(n, n, StandardRunStatus(s), p, Importance(i)) for n, s, p, i in runs], not_run
                )
                assert frozen == (domain.value, domain.failed_by_required_standard, domain.reason)
