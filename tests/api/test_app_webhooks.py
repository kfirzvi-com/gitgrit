"""App-level GitHub webhook handling (single shared App webhook).

App-delivered events carry an `installation` object and are verified against
GITHUB_APP_WEBHOOK_SECRET (not a per-project secret). Covers: a valid App-signed
delivery is accepted, an invalid signature is 401, and `installation.deleted`
removes the matching connection (cascading to its projects). Existing PAT
per-project webhook tests are unaffected (App branch requires the flag +
`installation` key, which those payloads lack).
"""
import hashlib
import hmac
import json

from django.test import override_settings
from model_bakery import baker
from rest_framework.test import APITestCase

from app.domain.models import AuthMethod, PlatformConnection, Project

APP_SECRET = "app-webhook-secret"


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_WEBHOOK_SECRET=APP_SECRET)
class TestGitHubAppWebhooks(APITestCase):
    url = "/api/webhooks/github/"

    def _post(self, payload: dict, secret: str | None, event: str):
        body = json.dumps(payload).encode()
        kwargs = {
            "data": body,
            "content_type": "application/json",
            "HTTP_X_GITHUB_EVENT": event,
        }
        if secret is not None:
            kwargs["HTTP_X_HUB_SIGNATURE_256"] = _sig(secret, body)
        return self.client.post(self.url, **kwargs)

    def _app_connection(self, tenant, installation_id):
        return baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.GITHUB_APP,
            access_token=None,
            installation_id=installation_id,
        )

    def test_valid_app_signed_push_is_accepted(self):
        tenant = baker.make("app.Tenant")
        conn = self._app_connection(tenant, 555)
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            platform="github",
            external_id="42",
        )
        payload = {
            "repository": {"id": 42},
            "ref": "refs/heads/main",
            "sender": {"login": "octocat"},
            "installation": {"id": 555},
        }
        resp = self._post(payload, secret=APP_SECRET, event="push")
        assert resp.status_code == 200
        assert resp.data["external_project_id"] == "42"
        assert "policies_run" in resp.data

    def test_invalid_app_signature_is_rejected(self):
        tenant = baker.make("app.Tenant")
        self._app_connection(tenant, 555)
        payload = {
            "repository": {"id": 42},
            "sender": {"login": "octocat"},
            "installation": {"id": 555},
        }
        resp = self._post(payload, secret="wrong-secret", event="push")
        assert resp.status_code == 401

    def test_installation_deleted_removes_connection_and_projects(self):
        tenant = baker.make("app.Tenant")
        conn = self._app_connection(tenant, 777)
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            platform="github",
            external_id="99",
        )
        payload = {"action": "deleted", "installation": {"id": 777}}
        resp = self._post(payload, secret=APP_SECRET, event="installation")
        assert resp.status_code == 200
        assert resp.data["removed"] >= 1
        assert not PlatformConnection.objects.filter(installation_id=777).exists()
        assert not Project.objects.filter(external_id="99").exists()

    def test_installation_repositories_added_and_removed_syncs_projects(self):
        tenant = baker.make("app.Tenant")
        conn = self._app_connection(tenant, 888)
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            platform="github",
            external_id="10",
        )
        payload = {
            "action": "added",
            "installation": {"id": 888},
            "repositories_added": [
                {"id": 20, "name": "new-repo", "full_name": "acme/new-repo"}
            ],
            "repositories_removed": [{"id": 10, "name": "old", "full_name": "acme/old"}],
        }
        resp = self._post(payload, secret=APP_SECRET, event="installation_repositories")
        assert resp.status_code == 200
        assert resp.data["added"] == 1
        assert resp.data["removed"] == 1
        assert Project.objects.filter(platform_connection=conn, external_id="20").exists()
        assert not Project.objects.filter(platform_connection=conn, external_id="10").exists()


@override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_WEBHOOK_SECRET=APP_SECRET)
class TestPatWebhookUnaffectedWhenAppEnabled(APITestCase):
    """A PAT per-repo webhook (no `installation` object) keeps using the
    per-project-secret path even while the App flag is on."""

    url = "/api/webhooks/github/"

    def test_pat_webhook_still_uses_per_project_secret(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github"
        )
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="333",
            webhook_secret="proj-secret",
        )
        body = json.dumps(
            {"repository": {"id": 333}, "sender": {"login": "octocat"}}
        ).encode()
        # Signed with the per-project secret (no installation key => PAT path).
        resp = self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="push",
            HTTP_X_HUB_SIGNATURE_256=_sig("proj-secret", body),
        )
        assert resp.status_code == 200
