"""Cockpit: warning lights read per project, with each project's own
importance for the standard."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.cockpit import Cockpit
from app.domain.models import CommitCheck, CommitScore, StandardExecution
from app.domain.score_representation import ScoreTone

Status = StandardExecution.Status


class CockpitTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.lint = baker.make("app.Standard", tenant=self.tenant, name="Lint", enabled=True)
        self.docs = baker.make("app.Standard", tenant=self.tenant, name="Docs", enabled=True)

    def _project(self, name, owner=""):
        project = baker.make("app.Project", tenant=self.tenant, name=name, owner=owner)
        project.standards.add(self.lint, self.docs)
        return project

    def _result(self, project, standard, status, importance="required", ago=None):
        execution = baker.make(
            "app.StandardExecution", project=project, standard=standard, standard_name=standard.name,
            score=0 if status != Status.PASSED else 100, status=status, importance=importance,
        )
        if ago:
            StandardExecution.objects.filter(pk=execution.pk).update(created_at=timezone.now() - ago)
        return execution

    def _lights(self):
        return {light.key: (light.count, light.lit) for light in Cockpit.for_workspace(self.tenant).lights}

    def test_lights_count_projects_by_kind_of_trouble(self):
        self._project("never-checked")

        self.assertEqual(self._lights(), {"failed": (0, False), "below_a": (0, False), "no_score": (1, True)})

    def test_a_failure_that_only_lowers_the_grade_is_named_in_its_row(self):
        api = self._project("api")
        self._result(api, self.lint, Status.FAILED, importance="major")

        [row] = Cockpit.for_workspace(self.tenant).rows

        self.assertEqual((row.project, row.below_par), (api, ("Lint",)))

    def test_rows_carry_their_projects_stacks(self):
        api = self._project("api")
        stack = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        component = api.components.first() or baker.make("app.Component", tenant=self.tenant, project=api)
        stack.components.add(component)

        [row] = Cockpit.for_workspace(self.tenant).rows

        self.assertEqual(row.stacks, ("Orders",))

    def test_other_workspaces_are_left_out(self):
        baker.make("app.Project")

        self.assertEqual(sum(count for count, _ in self._lights().values()), 0)
        self.assertEqual(Cockpit.for_workspace(self.tenant).rows, ())

    def test_last_check_is_the_newest_score_the_dashboard_reads(self):
        now = timezone.now()
        older = CommitScore(commit_sha="a" * 40, created_at=now - timedelta(hours=3))
        newer = CommitScore(commit_sha="b" * 40, created_at=now - timedelta(minutes=5))
        with mock.patch("app.application.cockpit.cockpit.scoring.project_scores", return_value={1: older, 2: newer}):
            self.assertIs(Cockpit.for_workspace(self.tenant).last_check, newer)

    def test_no_scores_no_last_check(self):
        self.assertIsNone(Cockpit.for_workspace(self.tenant).last_check)

    def test_checks_count_by_rolling_week_this_week_first(self):
        api = self._project("api")
        for weeks_ago in (0, 0, 1, 3):
            check = baker.make("app.CommitCheck", project=api)
            CommitCheck.objects.filter(pk=check.pk).update(created_at=timezone.now() - timedelta(weeks=weeks_ago, hours=1))
        baker.make("app.CommitCheck", project=self._project("old"))
        CommitCheck.objects.filter(project__name="old").update(created_at=timezone.now() - timedelta(weeks=6))

        cockpit = Cockpit.for_workspace(self.tenant)

        self.assertEqual(cockpit.checks_by_week, (2, 1, 0, 1))
        self.assertEqual((cockpit.checks_this_week, cockpit.checks_last_week, cockpit.checks_peak), (2, 1, 2))
