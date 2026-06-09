"""View tests for platform-connection management on workspace settings.

Covers the fix where the connection access token (a secret) must never be
rendered into the settings page, and is instead fetched on demand through an
authenticated, CSRF-protected endpoint.
"""
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

# A token containing characters that would have broken an inline JS string
# literal (single/double quotes) under the old onclick-interpolation approach.
SECRET_TOKEN = "ghp_secret's\"value-1234"


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestConnectionTokenReveal(TestCase):
    def _member_of(self, role):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role=role)
        self.client.force_login(user)
        return user, tenant

    def _connection(self, tenant, **kw):
        defaults = dict(
            tenant=tenant,
            platform="github",
            display_name="GitHub",
            base_url="https://api.github.com",
            access_token=SECRET_TOKEN,
        )
        defaults.update(kw)
        return baker.make("app.PlatformConnection", **defaults)

    def test_settings_page_never_renders_the_token(self):
        _, tenant = self._member_of("admin")
        self._connection(tenant)
        resp = self.client.get(reverse("tenant_settings"))
        assert resp.status_code == 200
        body = resp.content.decode()
        # The secret must not appear anywhere in the page source...
        assert SECRET_TOKEN not in body
        assert "ghp_secret" not in body
        # ...and the row action must not interpolate data into an inline
        # onclick handler (the old approach that broke on quotes and leaked
        # the token). It is driven by data-* attributes instead.
        assert 'onclick="openEditTokenModal' not in body
        assert "data-edit-token" in body

    def test_admin_can_reveal_token(self):
        _, tenant = self._member_of("admin")
        conn = self._connection(tenant)
        resp = self.client.post(
            reverse("reveal_connection_token", args=[conn.id])
        )
        assert resp.status_code == 200
        assert resp.json()["token"] == SECRET_TOKEN

    def test_member_cannot_reveal_token(self):
        _, tenant = self._member_of("member")
        conn = self._connection(tenant)
        resp = self.client.post(
            reverse("reveal_connection_token", args=[conn.id])
        )
        assert resp.status_code == 403

    def test_reveal_requires_post(self):
        _, tenant = self._member_of("admin")
        conn = self._connection(tenant)
        resp = self.client.get(reverse("reveal_connection_token", args=[conn.id]))
        assert resp.status_code == 405

    def test_anonymous_is_redirected(self):
        tenant = baker.make("app.Tenant")
        conn = self._connection(tenant)
        resp = self.client.post(reverse("reveal_connection_token", args=[conn.id]))
        assert resp.status_code == 302

    def test_cannot_reveal_token_of_other_tenant(self):
        _, tenant = self._member_of("admin")
        other_tenant = baker.make("app.Tenant")
        conn = self._connection(other_tenant)
        resp = self.client.post(
            reverse("reveal_connection_token", args=[conn.id])
        )
        # Scoped to request.tenant, so a connection in another workspace 404s.
        assert resp.status_code == 404
