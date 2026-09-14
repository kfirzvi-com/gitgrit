"""The polled results partial.

Manual runs happen in the background, so the project page's results cards are
served on their own from ``project_results`` and poll themselves while any
standard of the project is RUNNING — and stop polling once nothing is.
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

    def test_polls_while_a_standard_is_running(self):
        self._running_row()

        resp = self._get()

        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'hx-trigger="every 3s"' in body
        assert 'id="project-results"' in body
        # The running standard's Run button is disabled with a spinner.
        assert "btn-disabled" in body
        assert "loading-spinner" in body

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

    def test_the_project_page_polls_too(self):
        self._running_row()

        resp = self.client.get(reverse("project_detail", args=[self.project.pk]))

        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'hx-trigger="every 3s"' in body
