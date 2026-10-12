import secrets
from datetime import timedelta
from unittest.mock import patch

from django.test import Client
from django.utils import timezone
from model_bakery import baker
from oauth2_provider.models import AccessToken, Application, set_token_value
from rest_framework.test import APITestCase

from app.domain.models import APIToken, Standard

GOOD_CODE = 'def evaluate(project):\n    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'


def make_oauth_token(user, scope="read write", expires_in=3600) -> str:
    """An access token for the CLI client, stored the way DOT stores it."""
    raw = secrets.token_urlsafe(30)
    token = AccessToken(
        user=user,
        application=Application.objects.get(client_id="gitgrit-cli"),
        scope=scope,
        expires=timezone.now() + timedelta(seconds=expires_in),
    )
    set_token_value(token, raw)
    token.save()
    return raw


class PublicAPITestCase(APITestCase):
    def setUp(self):
        self.client = Client(headers={"host": "localhost"})
        self.user = baker.make("app.User", username="dev", email="dev@example.com")
        self.tenant = baker.make("app.Tenant", name="Acme")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.auth = {"Authorization": f"Bearer {make_oauth_token(self.user)}"}
        self.ws = f"/api/v1/workspaces/{self.tenant.id}"

    def get(self, url, **params):
        return self.client.get(url, params, headers=self.auth)

    def send(self, method, url, body=None):
        return getattr(self.client, method)(
            url, body or {}, content_type="application/json", headers=self.auth
        )


class TestAuthentication(PublicAPITestCase):
    def test_missing_token_is_401(self):
        r = self.client.get(f"{self.ws}/projects/")
        assert r.status_code == 401
        assert r["WWW-Authenticate"].startswith("Bearer")

    def test_invalid_tokens_are_401(self):
        for raw in ("grit_nope", "not-a-token"):
            r = self.client.get(f"{self.ws}/projects/", headers={"Authorization": f"Bearer {raw}"})
            assert r.status_code == 401, raw

    def test_expired_oauth_token_is_401(self):
        raw = make_oauth_token(self.user, expires_in=-1)
        r = self.client.get(f"{self.ws}/projects/", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 401

    def test_responses_carry_the_server_version(self):
        assert self.get("/api/v1/me/")["X-GitGrit-Version"] == "dev"
        assert self.client.get("/api/v1/me/")["X-GitGrit-Version"] == "dev"  # even a 401

    def test_json_only(self):
        r = self.client.post(
            f"{self.ws}/standards/", {"name": "x", "code": GOOD_CODE}, headers=self.auth
        )  # form-encoded
        assert r.status_code == 415

    def test_session_login_alone_is_not_enough(self):
        self.client.force_login(self.user)
        assert self.client.get(f"{self.ws}/projects/").status_code == 401

    def test_read_scope_cannot_write(self):
        self.auth = {"Authorization": f"Bearer {make_oauth_token(self.user, scope='read')}"}
        assert self.get(f"{self.ws}/standards/").status_code == 200
        r = self.send("post", f"{self.ws}/standards/", {"name": "x", "code": GOOD_CODE})
        assert r.status_code == 403

    def test_me_lists_every_workspace_for_oauth(self):
        other = baker.make("app.Tenant", name="Beta")
        baker.make("app.Membership", user=self.user, tenant=other, role="member")
        r = self.get("/api/v1/me/")
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == "dev@example.com"
        assert [(w["name"], w["role"]) for w in body["workspaces"]] == [
            ("Acme", "owner"), ("Beta", "member"),
        ]


class TestWorkspaceScoping(PublicAPITestCase):
    def test_workspace_you_are_not_in_is_404(self):
        foreign = baker.make("app.Tenant")
        r = self.get(f"/api/v1/workspaces/{foreign.id}/projects/")
        assert r.status_code == 404

    def test_oauth_token_reaches_every_member_workspace(self):
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=other, role="member")
        baker.make("app.Project", tenant=other, full_path="beta/api")
        r = self.get(f"/api/v1/workspaces/{other.id}/projects/")
        assert [p["full_path"] for p in r.json()] == ["beta/api"]

    def use_token(self, raw):
        self.auth = {"Authorization": f"Bearer {raw}"}

    def test_personal_token_acts_as_its_user_everywhere(self):
        other = baker.make("app.Tenant", name="Beta")
        baker.make("app.Membership", user=self.user, tenant=other, role="member")
        _, raw = APIToken.issue(name="laptop", created_by=self.user, user=self.user)
        assert raw.startswith("grit_pat_")
        self.use_token(raw)
        assert self.get(f"{self.ws}/projects/").status_code == 200
        assert self.get(f"/api/v1/workspaces/{other.id}/projects/").status_code == 200
        assert self.get(f"/api/v1/workspaces/{baker.make('app.Tenant').id}/projects/").status_code == 404
        me = self.get("/api/v1/me/").json()
        assert me["token_type"] == "personal_token"
        assert me["user"]["email"] == "dev@example.com"
        assert len(me["workspaces"]) == 2

    def test_personal_token_loses_a_workspace_with_the_membership(self):
        _, raw = APIToken.issue(name="laptop", created_by=self.user, user=self.user)
        self.use_token(raw)
        self.user.memberships.all().delete()
        assert self.get(f"{self.ws}/projects/").status_code == 404

    def test_personal_token_of_a_deactivated_user_is_401(self):
        _, raw = APIToken.issue(name="laptop", created_by=self.user, user=self.user)
        self.use_token(raw)
        self.user.is_active = False
        self.user.save()
        assert self.get("/api/v1/me/").status_code == 401

    def test_workspace_token_reaches_only_its_workspace(self):
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=other, role="member")
        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        assert raw.startswith("grit_ws_")
        self.use_token(raw)
        assert self.get(f"{self.ws}/projects/").status_code == 200
        assert self.get(f"/api/v1/workspaces/{other.id}/projects/").status_code == 404
        me = self.get("/api/v1/me/").json()
        assert me == {
            "token_type": "workspace_token",
            "user": None,
            "workspaces": [{"id": str(self.tenant.id), "name": "Acme", "role": None}],
        }

    def test_workspace_token_survives_its_creator_leaving(self):
        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.use_token(raw)
        self.user.delete()
        assert self.get(f"{self.ws}/projects/").status_code == 200

    def test_workspace_token_can_write_with_no_user(self):
        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.use_token(raw)
        r = self.send("post", f"{self.ws}/standards/", {"name": "From CI", "code": GOOD_CODE})
        assert r.status_code == 201, r.content
        version = Standard.objects.get(id=r.json()["id"]).versions.get()
        assert version.changed_by is None


class TestProjects(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.project = baker.make(
            "app.Project", tenant=self.tenant, name="backend",
            full_path="acme/backend", web_url="https://github.com/acme/backend",
            languages=["Python"],
        )
        baker.make("app.Project", tenant=baker.make("app.Tenant"), full_path="other/repo")

    def test_list_is_scoped_to_the_token_workspace(self):
        r = self.get(f"{self.ws}/projects/")
        assert r.status_code == 200
        assert [p["full_path"] for p in r.json()] == ["acme/backend"]

    def test_resolve_hit(self):
        r = self.get(f"{self.ws}/projects/resolve/", repo_full_path="acme/backend")
        assert r.status_code == 200
        assert r.json()["id"] == str(self.project.id)
        assert r.json()["matched_by"] == "full_path"

    def test_resolve_accepts_raw_git_remote(self):
        r = self.get(f"{self.ws}/projects/resolve/", web_url="git@github.com:acme/backend.git")
        assert r.status_code == 200

    def test_resolve_miss_is_404_with_candidates(self):
        r = self.get(f"{self.ws}/projects/resolve/", repo_full_path="acme/backnd")
        assert r.status_code == 404
        assert r.json()["candidates"] == ["acme/backend"]

    def test_status(self):
        r = self.get(f"{self.ws}/projects/{self.project.id}/status/")
        assert r.status_code == 200
        assert r.json()["project"]["name"] == "backend"
        assert r.json()["total_standards"] == 0

    def test_other_workspace_project_is_404(self):
        foreign = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        assert self.get(f"{self.ws}/projects/{foreign.id}/status/").status_code == 404
        assert self.get(f"{self.ws}/projects/{foreign.id}/standards/").status_code == 404

    def test_active_standards(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, code=GOOD_CODE, enabled=True, draft=False
        )
        self.project.standards.add(standard)
        r = self.get(f"{self.ws}/projects/{self.project.id}/standards/")
        assert r.status_code == 200
        assert [s["id"] for s in r.json()] == [str(standard.id)]
        assert "rules" in r.json()[0]

    def test_validate_edit(self):
        r = self.send(
            "post",
            f"{self.ws}/projects/{self.project.id}/validate-edit/",
            {"file_path": "README.md", "new_content": "hello"},
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True

    def test_validate_edit_requires_fields(self):
        r = self.send("post", f"{self.ws}/projects/{self.project.id}/validate-edit/", {})
        assert r.status_code == 400
        assert "file_path" in r.json()


class TestStandards(PublicAPITestCase):
    def test_create_get_update_delete(self):
        r = self.send("post", f"{self.ws}/standards/", {
            "name": "Has README", "code": GOOD_CODE, "events": ["push"], "labels": ["docs"],
        })
        assert r.status_code == 201, r.content
        standard_id = r.json()["id"]
        assert Standard.objects.get(id=standard_id).tenant == self.tenant

        r = self.get(f"{self.ws}/standards/{standard_id}/")
        assert r.status_code == 200
        assert r.json()["code"] == GOOD_CODE
        assert r.json()["labels"] == ["docs"]

        r = self.send("patch", f"{self.ws}/standards/{standard_id}/", {"draft": True})
        assert r.status_code == 200
        standard = Standard.objects.get(id=standard_id)
        assert standard.draft is True and standard.enabled is False
        assert standard.name == "Has README"  # untouched

        assert [s["id"] for s in self.get(f"{self.ws}/standards/").json()] == [standard_id]

        r = self.send("delete", f"{self.ws}/standards/{standard_id}/")
        assert r.status_code == 204
        assert not Standard.objects.filter(id=standard_id).exists()

    def test_create_rejects_code_without_evaluate(self):
        r = self.send("post", f"{self.ws}/standards/", {"name": "x", "code": "print(1)"})
        assert r.status_code == 400
        assert "evaluate" in r.json()["detail"]

    def test_create_rejects_unknown_event(self):
        r = self.send("post", f"{self.ws}/standards/", {
            "name": "x", "code": GOOD_CODE, "events": ["deploy"],
        })
        assert r.status_code == 400

    def test_foreign_standard_is_404(self):
        foreign = baker.make("app.Standard", tenant=baker.make("app.Tenant"), code=GOOD_CODE)
        assert self.get(f"{self.ws}/standards/{foreign.id}/").status_code == 404
        assert self.send("patch", f"{self.ws}/standards/{foreign.id}/", {"name": "x"}).status_code == 404
        assert self.send("delete", f"{self.ws}/standards/{foreign.id}/").status_code == 404
        assert Standard.objects.filter(id=foreign.id).exists()

    def test_dry_run(self):
        result = {"passed": True, "score": 100, "message": "OK", "details": {}}
        with patch(
            "app.presentation.api.views._sandbox.run_standard_test", return_value=result
        ) as run:
            r = self.send("post", f"{self.ws}/standards/test/", {
                "code": GOOD_CODE, "mock_input": {"default_branch": "main"},
            })
        assert r.status_code == 200
        assert r.json() == result
        run.assert_called_once_with(GOOD_CODE, {"default_branch": "main"})


class TestSchema(APITestCase):
    def test_schema_is_public_and_lists_only_v1(self):
        r = Client(headers={"host": "localhost"}).get(
            "/api/v1/schema/", headers={"Accept": "application/json"}
        )
        assert r.status_code == 200
        schema = r.json()
        assert schema["info"]["title"] == "GitGrit API"
        assert all(path.startswith("/api/v1/") for path in schema["paths"])
        assert "/api/v1/workspaces/{workspace_id}/standards/{standard_id}/" in schema["paths"]
        schemes = schema["components"]["securitySchemes"]
        assert schemes["bearerAuth"]["scheme"] == "bearer"
        assert set(schemes["oauth2"]["flows"]["authorizationCode"]["scopes"]) == {"read", "write"}
