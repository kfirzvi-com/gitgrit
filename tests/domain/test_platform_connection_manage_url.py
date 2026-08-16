"""Tests for PlatformConnection.github_app_manage_url — the read-only deep-link
surfaced in the settings connections table for App connections.

``TestCase`` subclass rather than bare pytest functions: CI runs
``manage.py test``, which collects only TestCase subclasses.
"""
from django.test import TestCase

from app.domain.models import AuthMethod, Platform, PlatformConnection, Tenant


class GitHubAppManageUrlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name="Acme", slug="acme-manage-url")

    def _conn(self, **kwargs):
        defaults = {
            "tenant": self.tenant,
            "platform": Platform.GITHUB,
            "display_name": "conn",
        }
        return PlatformConnection.objects.create(**{**defaults, **kwargs})

    def test_manage_url_for_organization_installation(self):
        conn = self._conn(
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=555,
            account_login="acme",
            account_type="Organization",
        )
        self.assertEqual(
            conn.github_app_manage_url,
            "https://github.com/organizations/acme/settings/installations/555",
        )

    def test_manage_url_for_user_installation(self):
        conn = self._conn(
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=999,
            account_login="octocat",
            account_type="User",
        )
        self.assertEqual(
            conn.github_app_manage_url,
            "https://github.com/settings/installations/999",
        )

    def test_manage_url_none_for_pat_connection(self):
        conn = self._conn(auth_method=AuthMethod.PAT, access_token="ghp_stored")
        self.assertIsNone(conn.github_app_manage_url)

    def test_manage_url_none_when_installation_id_missing(self):
        conn = self._conn(
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=None,
            account_login="acme",
            account_type="Organization",
        )
        self.assertIsNone(conn.github_app_manage_url)
