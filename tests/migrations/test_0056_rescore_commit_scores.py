"""0056 re-decides saved commit scores under "no score until every standard
has a result": an error, Required too, is no score before a failed Required
standard can fail the commit."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from model_bakery import baker

from app.domain.models import CommitScore, StandardExecution

migration = import_module("app.migrations.0056_rescore_commit_scores_no_score_first")
Status = StandardExecution.Status


class RescoreTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project")
        self.check = baker.make("app.CommitCheck", project=self.project, commit_sha="a" * 40)

    def saved(self, value, failed, reason, runs):
        score = baker.make(
            "app.CommitScore", project=self.project, commit_check=self.check, branch="main",
            commit_sha="a" * 40, value=value, failed=failed, reason=reason,
        )
        score.executions.set(
            baker.make(
                "app.StandardExecution", project=self.project, commit_check=self.check,
                standard_name=name, status=status, score=points, importance=importance,
            )
            for name, status, points, importance in runs
        )
        return score

    def rescored(self, score):
        migration.rescore(apps, None)
        score.refresh_from_db()
        return score.value, score.failed, score.reason

    def test_an_errored_required_standard_that_failed_the_commit_now_leaves_no_score(self):
        score = self.saved(None, True, "could not verify License", [
            ("License", Status.ERROR, 0, "required"), ("Readme", Status.PASSED, 100, "major"),
        ])

        assert self.rescored(score) == (None, False, "License errored")

    def test_an_errored_minor_standard_left_out_of_the_average_now_leaves_no_score(self):
        score = self.saved(100, False, "", [
            ("Changelog", Status.ERROR, 0, "minor"), ("Readme", Status.PASSED, 100, "major"),
        ])

        assert self.rescored(score) == (None, False, "Changelog errored")

    def test_a_failed_required_standard_with_another_errored_now_leaves_no_score(self):
        score = self.saved(None, True, "No secrets failing", [
            ("No secrets", Status.FAILED, 0, "required"), ("Changelog", Status.ERROR, 0, "minor"),
        ])

        assert self.rescored(score) == (None, False, "Changelog errored")

    def test_scores_the_rule_did_not_change_stay(self):
        failed = self.saved(None, True, "No secrets failing", [
            ("No secrets", Status.FAILED, 0, "required"), ("Readme", Status.PASSED, 100, "major"),
        ])
        scored = self.saved(67, False, "", [
            ("Readme", Status.PASSED, 100, "major"), ("Typos", Status.FAILED, 0, "minor"),
        ])

        assert self.rescored(failed) == (None, True, "No secrets failing")
        assert self.rescored(scored) == (67, False, "")

    def test_a_score_with_no_runs_on_record_is_left_alone(self):
        score = self.saved(80, False, "", [])

        assert self.rescored(score) == (80, False, "")

    def test_the_frozen_rule_matches_the_domain_rule(self):
        from app.domain.importance import Importance
        from app.domain.scoring import COMMIT_SCORING_POLICY, StandardRunResult, StandardRunStatus

        cases = [
            [("a", "passed", 90, "major"), ("b", "failed", 30, "minor")],
            [("a", "failed", 0, "required"), ("b", "passed", 100, "major")],
            [("a", "failed", 0, "required"), ("b", "error", 0, "minor")],
            [("a", "error", 0, "required")],
            [("a", "failed", 0, "major"), ("b", "failed", 0, "minor")],
        ]
        for runs in cases:
            with self.subTest(runs=runs):
                frozen = migration.decide([
                    StandardExecution(standard_name=n, status=s, score=p, importance=i) for n, s, p, i in runs
                ])
                domain = COMMIT_SCORING_POLICY.score_commit([
                    StandardRunResult(n, n, StandardRunStatus(s), p, Importance(i)) for n, s, p, i in runs
                ])
                assert frozen == (domain.value, domain.failed_by_required_standard, domain.reason)
