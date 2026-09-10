"""Webhook status on the project detail page.

GitHub App connections deliver events through the App's own webhook, so an
App-connected project never has a per-repo ``webhook_id``. The page must show
the webhook as active for those projects and must not offer "Register now",
which would try to create a repo hook the App has no permission for.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod

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
class TestProjectWebhookBadge(TestCase):
    def _get(self, project):
        resp = self.client.get(reverse("project_detail", args=[project.pk]))
        assert resp.status_code == 200
        return resp.content.decode()

    def test_github_app_project_shows_active_without_register_button(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=12345,
        )
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, webhook_id=""
        )

        body = self._get(project)
        assert "via GitHub App" in body
        assert "Not registered" not in body
        assert "Register now" not in body

    def test_pat_project_without_webhook_offers_register(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.PAT,
        )
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, webhook_id=""
        )

        body = self._get(project)
        assert "Not registered" in body
        assert "Register now" in body

    def test_pat_project_with_webhook_shows_id(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.PAT,
        )
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, webhook_id="987"
        )

        body = self._get(project)
        assert "ID: 987" in body
        assert "Register now" not in body
