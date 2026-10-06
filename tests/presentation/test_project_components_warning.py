"""The project page's Components card shows a failed dependency-graph build."""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

ALERT = "The dependency graph could not be rebuilt"


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestComponentsWarning(TestCase):
    def _page(self, **project_kw):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        project = baker.make("app.Project", tenant=tenant, **project_kw)
        self.client.force_login(user)
        resp = self.client.get(reverse("project_detail", args=[project.pk]))
        assert resp.status_code == 200
        return resp.content.decode()

    def test_failed_graph_shows_alert_and_error(self):
        body = self._page(deps_status="failed", deps_error="LLM provider returned 429")
        assert 'id="components"' in body
        assert "alert-warning" in body
        assert ALERT in body
        assert "LLM provider returned 429" in body

    def test_ok_graph_shows_no_alert(self):
        body = self._page(deps_status="ok")
        assert 'id="components"' in body
        assert ALERT not in body
