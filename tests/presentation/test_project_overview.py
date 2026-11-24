"""The project page's Overview: a summary of every tab — the score, delivery
and pull requests at a glance and recent activity in one main column, the
project's details beside it — each linking to the tab with more."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.delivery import DeliveryReport
from app.domain.delivery import DeploymentStrategy
from app.models import DeliverySettings, Deployment, Platform
from app.presentation.project_overview import ProjectOverview


def result(name, status, importance="default"):
    return SimpleNamespace(standard_name=name, status=status, importance=importance)


class ProjectOverviewTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.project = baker.make("app.Project", platform=Platform.GITHUB, default_branch="main",
                                  web_url="https://github.com/acme/shop")
        self.settings = DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS,
                                                        refreshed_at=self.now)

    def overview(self, results=None):
        results = {"attached_standards": [object()], "project_has_score": True, "latest_executions": [], **(results or {})}
        return ProjectOverview(self.project, results, DeliveryReport.for_project(self.project), now=self.now)

    def test_activity_mixes_deployments_merges_and_runs_newest_first(self):
        baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, ref="v2.0.0",
                   external_id="v2.0.0", deployed_at=self.now - timedelta(hours=1))
        baker.make("app.PullRequest", project=self.project, number=9, title="Faster checkout", state="merged",
                   created_at=self.now - timedelta(days=1), merged_at=self.now - timedelta(hours=3),
                   closed_at=self.now - timedelta(hours=3), updated_at=self.now)
        run = SimpleNamespace(standard_name="Lint", status="passed", created_at=self.now - timedelta(hours=2),
                              get_status_display=lambda: "Passed")

        items = self.overview({"recent_executions": [run]}).activity

        self.assertEqual([i.text for i in items], ["Deployed v2.0.0", "Lint passed", "Merged #9 Faster checkout"])


class OverviewPageTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_needs_attention_is_gone(self):
        project = baker.make("app.Project", tenant=self.tenant, platform=Platform.GITHUB)
        DeliverySettings.objects.create(project=project, refreshed_at=timezone.now())

        response = self.client.get(reverse("project_detail", args=[project.pk]))

        self.assertNotContains(response, "data-overview-attention")

    def test_a_git_project_summarises_delivery_and_links_to_each_tab(self):
        project = baker.make("app.Project", tenant=self.tenant, platform=Platform.GITHUB)
        DeliverySettings.objects.create(project=project, refreshed_at=timezone.now())

        response = self.client.get(reverse("project_detail", args=[project.pk]))

        for marker in ("data-overview-main", "data-overview-delivery", "data-overview-pulls", "data-overview-activity",
                       "data-overview-sidebar"):
            self.assertContains(response, marker)
        self.assertContains(response, 'data-open-tab="delivery"')

    def test_a_first_visit_starts_the_first_delivery_sync(self):
        project = baker.make("app.Project", tenant=self.tenant, platform=Platform.GITHUB)

        with mock.patch("app.tasks.sync_delivery.configure") as configure:
            response = self.client.get(reverse("project_detail", args=[project.pk]))

        configure.return_value.defer.assert_called_once()
        self.assertContains(response, "Syncing from")

    def test_an_uploaded_build_has_no_delivery(self):
        project = baker.make("app.Project", tenant=self.tenant, platform=Platform.ARTIFACT)

        response = self.client.get(reverse("project_detail", args=[project.pk]))

        self.assertNotContains(response, "data-overview-delivery")
        self.assertContains(response, "data-overview-activity")
