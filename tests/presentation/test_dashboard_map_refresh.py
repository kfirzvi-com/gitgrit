"""The map is off the dashboard for now; the refresh endpoint is kept and
lets a superuser rebuild it from every project's main branch.

The refresh button queues the per-project dependency job for each project in
the workspace (each run reads the project's default branch); the "last update"
line shows the newest successful refresh as DD/MM/YY (or --- when no project was
ever analyzed); while a run is queued or running the button is disabled. Refreshing costs one LLM run per project, so only
superusers get the button and the endpoint."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.domain.models import Project

CONFIGURE = "app.tasks.infer_project_dependencies.configure"


class DashboardMapRefreshTests(TestCase):
    def setUp(self):
        # GitGrit always keeps one superuser, so another one lets the tests
        # take the flag off this user.
        baker.make("app.User", is_superuser=True)
        self.user = baker.make("app.User", is_superuser=True)
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.stack = baker.make("app.Stack", tenant=self.tenant)
        self.old = baker.make(
            "app.Project", tenant=self.tenant,
            deps_status=Project.DepsStatus.OK,
            deps_analyzed_at=timezone.now() - timedelta(days=2),
        )
        self.new = baker.make(
            "app.Project", tenant=self.tenant,
            deps_status=Project.DepsStatus.OK,
            deps_analyzed_at=timezone.now() - timedelta(hours=3),
        )
        self.other_tenant_project = baker.make("app.Project", deps_status=Project.DepsStatus.OK)

    def test_dashboard_no_longer_builds_or_shows_the_map(self):
        # The map is off the dashboard for now: no graph is built, no refresh
        # button, no diagram scripts. The refresh endpoint below is kept.
        response = self.client.get(reverse("dashboard"))

        self.assertNotIn("architecture_data", response.context)
        self.assertNotContains(response, 'id="architecture-flow"')
        self.assertNotContains(response, reverse("refresh_map"))
        self.assertNotContains(response, "architecture-diagram.js")

    def test_refresh_queues_every_workspace_project_from_its_main_branch(self):
        with mock.patch(CONFIGURE) as configure:
            response = self.client.post(reverse("refresh_map"))

        self.assertRedirects(response, reverse("dashboard"))
        queued = {c.kwargs["project_id"] for c in configure.return_value.defer.call_args_list}
        self.assertEqual(queued, {str(self.old.pk), str(self.new.pk)})
        locks = {c.kwargs["queueing_lock"] for c in configure.call_args_list}
        self.assertEqual(locks, {f"deps:{self.old.pk}", f"deps:{self.new.pk}"})
        self.assertEqual(
            set(Project.objects.filter(tenant=self.tenant).values_list("deps_status", flat=True)),
            {Project.DepsStatus.PENDING},
        )
        self.other_tenant_project.refresh_from_db()
        self.assertEqual(self.other_tenant_project.deps_status, Project.DepsStatus.OK)

    def test_refresh_flashes_how_many_projects_were_queued(self):
        with mock.patch(CONFIGURE):
            response = self.client.post(reverse("refresh_map"), follow=True)

        self.assertContains(response, "Refreshing the map from the main branch of 2 projects")

    def test_refresh_with_no_projects_warns(self):
        Project.objects.filter(tenant=self.tenant).delete()

        with mock.patch(CONFIGURE) as configure:
            response = self.client.post(reverse("refresh_map"), follow=True)

        configure.return_value.defer.assert_not_called()
        self.assertContains(response, "No projects to refresh.")

    def test_member_cannot_refresh(self):
        self.user.is_superuser = False
        self.user.save()

        with mock.patch(CONFIGURE) as configure:
            response = self.client.post(reverse("refresh_map"))

        self.assertEqual(response.status_code, 403)
        configure.return_value.defer.assert_not_called()
        self.old.refresh_from_db()
        self.assertEqual(self.old.deps_status, Project.DepsStatus.OK)

    def test_refresh_is_post_only(self):
        with mock.patch(CONFIGURE) as configure:
            response = self.client.get(reverse("refresh_map"))

        self.assertEqual(response.status_code, 405)
        configure.return_value.defer.assert_not_called()

    def test_refresh_requires_login(self):
        self.client.logout()

        with mock.patch(CONFIGURE) as configure:
            response = self.client.post(reverse("refresh_map"))

        self.assertEqual(response.status_code, 302)
        configure.return_value.defer.assert_not_called()
