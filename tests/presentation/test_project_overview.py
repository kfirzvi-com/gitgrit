"""The project page's Overview: a summary of every tab — the score, delivery
and pull requests at a glance, what needs attention and recent activity —
each linking to the tab with more."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.delivery import DeliveryReport
from app.domain.delivery import DeploymentStrategy
from app.models import DeliverySettings, Deployment, Platform, StandardExecution
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

    def test_failed_standards_come_first_required_apart(self):
        failed, error = StandardExecution.Status.FAILED, StandardExecution.Status.ERROR
        items = self.overview({"latest_executions": [
            result("Secrets", failed, "required"), result("Lint", failed), result("Docs", failed), result("LLM", error),
        ]}).attention

        self.assertEqual([(i.text, i.tone, i.tab) for i in items], [
            ("1 Required standard failed", "failed", "results"),
            ("2 standards failed", "needs_attention", "results"),
            ("1 standard could not run", "needs_attention", "results"),
        ])
        self.assertEqual(items[1].detail, "Lint, Docs")

    def test_stale_delivery_wants_a_look(self):
        self.settings.pending_commits, self.settings.oldest_pending_at = 4, self.now - timedelta(days=9)
        self.settings.refresh_error = "The GitHub token can't read this repository's deployments."
        self.settings.save()
        baker.make("app.PullRequest", project=self.project, number=5, title="Old idea", state="open",
                   created_at=self.now - timedelta(days=12), updated_at=self.now)

        texts = [item.text for item in self.overview().attention]

        self.assertEqual(texts, [
            "Delivery data is incomplete", "4 commits waiting to ship", "1 pull request open over a week",
        ])

    def test_no_score_and_no_standards_say_so(self):
        self.assertEqual(self.overview({"project_has_score": False}).attention[0].text, "No score on main yet")
        self.assertEqual(self.overview({"attached_standards": []}).attention[0].tab, "standards")

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

    def test_a_git_project_summarises_delivery_and_links_to_each_tab(self):
        project = baker.make("app.Project", tenant=self.tenant, platform=Platform.GITHUB)
        DeliverySettings.objects.create(project=project, refreshed_at=timezone.now())

        response = self.client.get(reverse("project_detail", args=[project.pk]))

        for marker in ("data-overview-delivery", "data-overview-pulls", "data-overview-attention", "data-overview-activity"):
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
        self.assertContains(response, "data-overview-attention")
