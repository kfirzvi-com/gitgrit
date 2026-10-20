"""Every screen that shows project health ignores runs on other branches: the
project page, the badge, the dashboard, the project status service and the
notifications pane all read the same current results."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.project_health_service import ProjectHealthService
from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution

Status = StandardExecution.Status


class HealthIgnoresOtherBranchesTests(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Pinned CI")
        self.project.standards.add(self.standard)
        main = baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", score=100, status=Status.PASSED, ref="refs/heads/main",
        )
        StandardExecution.objects.filter(pk=main.pk).update(created_at=timezone.now() - timedelta(hours=1))
        # A newer failing run on a feature branch: it must not move health.
        self.branch_run = baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", score=0, status=Status.FAILED, ref="refs/heads/feature/wip",
        )

    def test_project_page_grades_the_default_branch_but_lists_the_branch_run(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]))

        self.assertEqual(response.context["grade"].letter, "A+")
        self.assertIn(self.branch_run, list(response.context["recent_executions"]))

    def test_badge_grades_the_default_branch(self):
        response = self.client.get(reverse("project_badge", args=[self.project.pk]))

        self.assertIn(">A+<", response.content.decode())

    def test_dashboard_has_nothing_needing_attention(self):
        baker.make("app.Stack", tenant=self.tenant)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["attention_items"], [])
        self.assertEqual(response.context["workspace_grade"], "A+")

    def test_project_status_service_grades_the_default_branch(self):
        status = ProjectStatusService().get_project_status(self.tenant, str(self.project.pk))

        self.assertEqual((status["grade"], status["reason"]), ("A+", "perfect"))
        self.assertEqual(status["overall_score"], 100)
        self.assertEqual(status["failed"], 0)

    def test_health_api_service_grades_the_default_branch(self):
        health = ProjectHealthService().health(self.tenant, str(self.project.pk))

        self.assertEqual((health["grade"], health["level"], health["score"]), ("A+", "good", 100))
