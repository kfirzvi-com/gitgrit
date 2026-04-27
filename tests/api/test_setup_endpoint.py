from model_bakery import baker
from django.test import Client
from rest_framework.test import APITestCase

from app.domain.models import APIToken


class TestSetupHTTPEndpoint(APITestCase):
    """GET /api/setup/<client> — kind-gated bearer-auth'd rule-file delivery."""

    def setUp(self):
        self.client = Client(headers={"host": "localhost"})
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")

    def _make_token(self, kind: str) -> str:
        token, raw = APIToken.generate(client_kind=kind)
        token.user = self.user
        token.tenant = self.tenant
        token.name = f"test-{kind}"
        token.save()
        return raw

    def test_missing_bearer_returns_401(self):
        r = self.client.get("/api/setup/cursor/")
        assert r.status_code == 401
        assert r.json() == {"error": "missing_bearer_token"}

    def test_invalid_token_returns_401(self):
        r = self.client.get(
            "/api/setup/cursor/", headers={"Authorization": "Bearer grit_invalid"}
        )
        assert r.status_code == 401
        assert r.json() == {"error": "invalid_token"}

    def test_claude_token_blocked_with_403(self):
        raw = self._make_token("claude")
        r = self.client.get(
            "/api/setup/cursor/", headers={"Authorization": f"Bearer {raw}"}
        )
        assert r.status_code == 403
        assert r.json()["error"] == "not_applicable"

    def test_generic_token_returns_cursor_mdc(self):
        raw = self._make_token("generic")
        r = self.client.get(
            "/api/setup/cursor/", headers={"Authorization": f"Bearer {raw}"}
        )
        assert r.status_code == 200
        assert r["Content-Type"].startswith("text/plain")
        body = r.content.decode()
        assert "alwaysApply: true" in body
        assert "validate_edit" in body

    def test_generic_token_returns_clinerules(self):
        raw = self._make_token("generic")
        r = self.client.get(
            "/api/setup/cline/", headers={"Authorization": f"Bearer {raw}"}
        )
        assert r.status_code == 200
        body = r.content.decode()
        assert "validate_edit" in body
        # Cline output is plain markdown, no frontmatter
        assert not body.startswith("---")

    def test_unsupported_client_returns_404(self):
        raw = self._make_token("generic")
        r = self.client.get(
            "/api/setup/vim/", headers={"Authorization": f"Bearer {raw}"}
        )
        assert r.status_code == 404
        assert r.json()["error"] == "unsupported_client"
        assert "cursor" in r.json()["supported"]
