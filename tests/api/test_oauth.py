"""The CLI's OAuth 2.0 login, end to end through django-oauth-toolkit:
authorization code + PKCE (S256) with an RFC 8252 loopback redirect."""
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from django.test import Client
from model_bakery import baker
from oauth2_provider.models import AccessToken
from rest_framework.test import APITestCase

CLIENT_ID = "gitgrit-cli"
REDIRECT = "http://127.0.0.1:53682/callback"


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class OAuthTestCase(APITestCase):
    def setUp(self):
        self.client = Client(headers={"host": "localhost"})
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant", name="Acme")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.verifier, self.challenge = pkce_pair()
        self.params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "scope": "read write",
            "state": "xyz",
        }

    def authorize_url(self, **overrides):
        return "/oauth/authorize/?" + urlencode({**self.params, **overrides})

    def approve(self, **overrides):
        self.client.force_login(self.user)
        r = self.client.post(
            "/oauth/authorize/", {**self.params, **overrides, "allow": "Authorize"}
        )
        assert r.status_code == 302, r.content
        return r["Location"]

    def code(self, **overrides):
        query = parse_qs(urlsplit(self.approve(**overrides)).query)
        assert query["state"] == ["xyz"]
        return query["code"][0]

    def token(self, **data):
        return self.client.post("/oauth/token/", {"client_id": CLIENT_ID, **data})

    def exchange(self, code, **overrides):
        return self.token(**{
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": self.verifier,
            **overrides,
        })


class TestAuthorize(OAuthTestCase):
    def test_anonymous_user_is_sent_to_login_and_back(self):
        r = self.client.get(self.authorize_url())
        assert r.status_code == 302
        assert r["Location"].startswith("/accounts/login/")
        assert "next=/oauth/authorize/" in r["Location"]

    def test_consent_page(self):
        self.client.force_login(self.user)
        r = self.client.get(self.authorize_url())
        assert r.status_code == 200
        assert b"Authorize GitGrit CLI" in r.content
        assert b"Create, edit and delete standards" in r.content

    def test_any_loopback_port_is_accepted(self):
        location = self.approve(redirect_uri="http://127.0.0.1:9/callback")
        assert location.startswith("http://127.0.0.1:9/callback?")

    def test_non_loopback_redirect_is_refused_without_redirecting(self):
        self.client.force_login(self.user)
        r = self.client.get(self.authorize_url(redirect_uri="https://evil.example/callback"))
        assert r.status_code == 400
        assert "Location" not in r
        assert b"Authorization failed" in r.content

    def test_pkce_is_required(self):
        self.client.force_login(self.user)
        params = {k: v for k, v in self.params.items() if not k.startswith("code_challenge")}
        r = self.client.get("/oauth/authorize/?" + urlencode(params))
        location = r.get("Location", "")
        assert "code=" not in location
        assert "error=" in location or b"Authorization failed" in r.content

    def test_plain_pkce_is_refused(self):
        self.client.force_login(self.user)
        r = self.client.get(
            self.authorize_url(code_challenge=self.verifier, code_challenge_method="plain")
        )
        assert "code=" not in r.get("Location", "")

    def test_cancel_denies(self):
        self.client.force_login(self.user)
        r = self.client.post("/oauth/authorize/", self.params)
        assert parse_qs(urlsplit(r["Location"]).query)["error"] == ["access_denied"]

    def test_unknown_client(self):
        self.client.force_login(self.user)
        r = self.client.get(self.authorize_url(client_id="evil"))
        assert "code=" not in r.get("Location", "")


class TestTokenExchange(OAuthTestCase):
    def test_full_flow_issues_a_token_that_works_on_the_api(self):
        r = self.exchange(self.code())
        assert r.status_code == 200, r.content
        body = r.json()
        assert body["token_type"] == "Bearer"
        assert set(body["scope"].split()) == {"read", "write"}
        assert body["refresh_token"]

        # Stored hashed (RFC 9700), never in plaintext.
        assert AccessToken.objects.get().token == ""

        api = Client(headers={"host": "localhost"})
        auth = {"Authorization": f"Bearer {body['access_token']}"}
        me = api.get("/api/v1/me/", headers=auth)
        assert me.status_code == 200
        assert me.json()["workspaces"][0]["id"] == str(self.tenant.id)
        projects = api.get(f"/api/v1/workspaces/{self.tenant.id}/projects/", headers=auth)
        assert projects.status_code == 200

    def test_wrong_verifier_is_refused(self):
        r = self.exchange(self.code(), code_verifier=pkce_pair()[0])
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    def test_code_is_single_use(self):
        code = self.code()
        assert self.exchange(code).status_code == 200
        assert self.exchange(code).status_code == 400

    def test_redirect_uri_must_match(self):
        r = self.exchange(self.code(), redirect_uri="http://127.0.0.1:1/other")
        assert r.status_code == 400

    def test_refresh_rotates_and_old_refresh_token_dies(self):
        first = self.exchange(self.code()).json()
        r = self.token(grant_type="refresh_token", refresh_token=first["refresh_token"])
        assert r.status_code == 200, r.content
        second = r.json()
        assert second["refresh_token"] != first["refresh_token"]
        reuse = self.token(grant_type="refresh_token", refresh_token=first["refresh_token"])
        assert reuse.status_code == 400

    def test_password_grant_is_refused(self):
        r = self.token(grant_type="password", username="x", password="y")
        assert r.status_code == 400


class TestRevokeAndDiscovery(OAuthTestCase):
    def test_revoke(self):
        access = self.exchange(self.code()).json()["access_token"]
        r = self.client.post("/oauth/revoke_token/", {"token": access, "client_id": CLIENT_ID})
        assert r.status_code == 200
        me = Client(headers={"host": "localhost"}).get(
            "/api/v1/me/", headers={"Authorization": f"Bearer {access}"}
        )
        assert me.status_code == 401

    def test_server_metadata(self):
        r = self.client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        body = r.json()
        assert body["authorization_endpoint"] == "http://localhost/oauth/authorize/"
        assert body["token_endpoint"] == "http://localhost/oauth/token/"
        assert body["code_challenge_methods_supported"] == ["S256"]
        assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
        assert "introspection_endpoint" not in body
