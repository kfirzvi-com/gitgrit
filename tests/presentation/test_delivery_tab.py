"""The project page's Delivery tab: the first visit starts a look for
deployments, the tab polls while one runs, and saving settings recounts."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.domain.delivery import DeploymentStrategy
from app.models import DeliverySettings, Deployment


class DeliveryTabTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, web_url="https://github.com/acme/shop")
        patcher = mock.patch("app.tasks.sync_delivery.configure")
        self.configure = patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, name="project_delivery"):
        return reverse(name, args=[self.project.pk])

    def test_the_first_visit_starts_a_look_for_deployments_and_polls(self):
        response = self.client.get(self.url())

        self.configure.return_value.defer.assert_called_once()
        self.assertContains(response, 'hx-trigger="every 2s"')
        self.assertContains(response, "Looking for deployments")

    def test_once_refreshed_it_shows_the_frequency_and_stops_polling(self):
        now = timezone.now()
        DeliverySettings.objects.create(
            project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS,
            refresh_requested_at=now - timedelta(minutes=1), refreshed_at=now,
        )
        baker.make(
            Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS,
            external_id="v1.0.0", sha="a" * 40, ref="v1.0.0", deployed_at=now - timedelta(days=1),
        )

        response = self.client.get(self.url())

        self.configure.return_value.defer.assert_not_called()
        self.assertNotContains(response, 'hx-trigger="every 2s"')
        self.assertContains(response, 'data-strategy-in-use="release_tags"')
        self.assertContains(response, "v1.0.0")
        self.assertContains(response, f"https://github.com/acme/shop/commit/{'a' * 40}")

    def test_another_workspaces_project_is_not_found(self):
        other = baker.make("app.Project")

        self.assertEqual(self.client.get(reverse("project_delivery", args=[other.pk])).status_code, 404)

    def test_saving_a_new_strategy_recounts(self):
        response = self.client.post(
            self.url("project_delivery_settings"),
            {"strategy": "deploy_branch", "deploy_branch": "live", "release_tag_pattern": "v*"},
        )

        settings = DeliverySettings.objects.get(project=self.project)
        self.assertEqual((settings.strategy, settings.deploy_branch), ("deploy_branch", "live"))
        self.configure.return_value.defer.assert_called_once()
        self.assertContains(response, "Looking for deployments")

    def test_a_deploy_workflow_needs_its_file_name(self):
        response = self.client.post(
            self.url("project_delivery_settings"),
            {"strategy": "deploy_workflow", "deploy_workflow": "", "deploy_branch": "production", "release_tag_pattern": "v*"},
        )

        self.assertContains(response, "Name the workflow file that deploys.")
        self.assertEqual(DeliverySettings.objects.get(project=self.project).strategy, "auto")

    def test_refresh_asks_for_another_look(self):
        self.client.post(self.url("project_delivery_refresh"))

        self.configure.return_value.defer.assert_called_once()

    def test_refresh_right_after_a_sync_waits_and_says_when_it_works_again(self):
        DeliverySettings.objects.create(project=self.project, refreshed_at=timezone.now() - timedelta(minutes=1))

        response = self.client.post(self.url("project_delivery_refresh"))

        self.configure.assert_not_called()
        self.assertContains(response, "Refresh works again in")
        self.assertContains(response, "syncs every 15 minutes")

    def test_shows_the_running_version_and_links_what_waits_to_ship(self):
        DeliverySettings.objects.create(
            project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, refreshed_at=timezone.now(),
            pending_commits=5, oldest_pending_at=timezone.now() - timedelta(days=3),
        )
        self.project.default_branch = "main"
        self.project.save()
        baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, ref="v2.0.0",
                   external_id="v2.0.0", sha="f" * 40, deployed_at=timezone.now() - timedelta(days=2))

        response = self.client.get(self.url())

        self.assertContains(response, 'href="https://github.com/acme/shop/releases/tag/v2.0.0"')
        self.assertContains(response, 'data-pending-commits="5"')
        self.assertContains(response, f'href="https://github.com/acme/shop/compare/{"f" * 40}...main"')
