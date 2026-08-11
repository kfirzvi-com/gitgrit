"""The project-import path skips per-repo webhook creation for GitHub App
connections (events arrive through the App's own webhook), but still registers
a per-repo webhook for PAT connections.
"""
from unittest import mock

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod


@pytest.mark.django_db
class TestImportWebhookBranch(TestCase):
    def _login_owner(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        return user, tenant

    def _connection(self, tenant, auth_method):
        return baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=auth_method,
            access_token=None if auth_method == AuthMethod.GITHUB_APP else "ghp_x",
        )

    def _post_import(self, connection):
        return self.client.post(
            reverse("add_project_search", args=[connection.id]),
            data={
                "external_id": "555",
                "name": "app",
                "full_path": "acme/app",
                "web_url": "https://github.com/acme/app",
                "default_branch": "main",
                "description": "",
                "lifecycle": "development",
            },
        )

    def _mock_client(self):
        client = mock.Mock()
        client.get_languages.return_value = []
        client.get_topics.return_value = []
        client.create_webhook.return_value = "hook-123"
        return client

    def test_app_connection_skips_webhook_creation(self):
        _, tenant = self._login_owner()
        conn = self._connection(tenant, AuthMethod.GITHUB_APP)
        client = self._mock_client()
        with mock.patch(
            "app.presentation.views.project_views.get_platform_client",
            return_value=client,
        ):
            resp = self._post_import(conn)
        assert resp.status_code == 302
        client.create_webhook.assert_not_called()

        from app.domain.models import Project

        project = Project.objects.get(tenant=tenant, external_id="555")
        assert project.webhook_id == ""
        assert project.webhook_secret == ""

    def test_pat_connection_still_creates_webhook(self):
        _, tenant = self._login_owner()
        conn = self._connection(tenant, AuthMethod.PAT)
        client = self._mock_client()
        with mock.patch(
            "app.presentation.views.project_views.get_platform_client",
            return_value=client,
        ):
            resp = self._post_import(conn)
        assert resp.status_code == 302
        client.create_webhook.assert_called_once()

        from app.domain.models import Project

        project = Project.objects.get(tenant=tenant, external_id="555")
        assert project.webhook_id == "hook-123"
