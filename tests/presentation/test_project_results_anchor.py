"""The ``#compliance`` anchor that ``standards.failing`` notices link to, and the
``#project-results`` wrapper around it.

Both must exist on the full page and survive the HTMX poll that swaps it in place.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectResultsAnchor(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=tenant)

    def test_project_page_has_the_anchor(self):
        resp = self.client.get(reverse("project_detail", args=[self.project.pk]))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'id="compliance"' in body

    def test_poll_partial_keeps_the_anchor(self):
        resp = self.client.get(reverse("project_results", args=[self.project.pk]))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'id="compliance"' in body
