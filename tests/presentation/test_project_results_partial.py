"""The Standards card partial.

It lists the attached standards and opens Manage; it has no run buttons and
never polls. Runs start from the Health card (a branch or one commit), which
follows them while they are in flight.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectResultsPartial(TestCase):
    def setUp(self):
        _, self.tenant = _login_member(self.client)
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.standard = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        self.project.standards.add(self.standard)

    def _get(self):
        return self.client.get(reverse("project_results", args=[self.project.pk]))

    def _running_row(self):
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            standard_name=self.standard.name,
            status=StandardExecution.Status.RUNNING,
        )

    def test_never_polls_and_has_no_run_buttons_even_while_running(self):
        self._running_row()

        resp = self._get()

        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'hx-trigger="every 3s"' not in body
        assert reverse("run_project_standards", args=[self.project.pk]) not in body
        assert "loading-spinner" not in body

    def test_does_not_poll_when_nothing_is_running(self):
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            standard_name=self.standard.name,
            status=StandardExecution.Status.PASSED,
        )

        resp = self._get()

        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'hx-trigger="every 3s"' not in body
        assert 'id="project-results"' in body

    def test_another_tenants_project_is_not_found(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))

        resp = self.client.get(reverse("project_results", args=[other.pk]))

        assert resp.status_code == 404

    def test_the_project_page_leaves_following_runs_to_the_health_card(self):
        self._running_row()

        resp = self.client.get(reverse("project_detail", args=[self.project.pk]))

        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'hx-trigger="every 3s"' not in body
        assert reverse("project_history", args=[self.project.pk]) in body
