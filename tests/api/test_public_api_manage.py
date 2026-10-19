"""Setting a workspace up over the public API: connections, repositories,
projects, attached standards, turning standards on and off, and the
marketplace — everything the web UI does on the way to a first score."""
from unittest import mock

from model_bakery import baker

from app.domain.models import APIToken, AuthMethod, PlatformConnection, Project, Standard
from tests.api.test_public_api import PublicAPITestCase

REPOS = [
    {"external_id": "101", "name": "auth-service", "full_path": "acme/auth-service",
     "web_url": "https://github.com/acme/auth-service", "default_branch": "main", "description": ""},
    {"external_id": "102", "name": "api-gateway", "full_path": "acme/api-gateway",
     "web_url": "https://github.com/acme/api-gateway", "default_branch": "main", "description": ""},
]


def _platform():
    client = mock.Mock()
    client.search_projects.side_effect = lambda q="": [
        dict(r) for r in REPOS if q.lower() in r["full_path"].lower()
    ]
    client.get_languages.return_value = ["Python"]
    client.get_topics.return_value = []
    client.create_webhook.return_value = "hook-1"
    return client


class ManageAPITestCase(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.connection = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github",
            display_name="GitHub App (acme)", auth_method=AuthMethod.GITHUB_APP,
            account_login="acme", access_token="secret-token",
        )
        self.readme = baker.make("app.Standard", tenant=self.tenant, name="README Exists", enabled=True, draft=False)
        self.platform = self._patch("app.application.project_management.get_platform_client", return_value=_platform())
        self._patch("app.application.standard_runs.run_standards.configure")

    def _patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def as_workspace_token(self):
        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.auth = {"Authorization": f"Bearer {raw}"}

    def as_member(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        _, raw = APIToken.issue(name="laptop", created_by=member, user=member)
        self.auth = {"Authorization": f"Bearer {raw}"}


class TestConnections(ManageAPITestCase):
    def test_list_never_returns_tokens(self):
        r = self.get(f"{self.ws}/connections/")

        assert r.status_code == 200
        [c] = r.json()
        assert c["auth_method"] == "github_app" and c["account_login"] == "acme"
        assert "secret-token" not in r.content.decode()

    def test_an_admin_connects_a_platform_with_a_token(self):
        r = self.send("post", f"{self.ws}/connections/", {"platform": "gitlab", "access_token": "glpat-x"})

        assert r.status_code == 201
        assert r.json()["display_name"] == "GitLab"
        assert PlatformConnection.objects.get(pk=r.json()["id"]).access_token == "glpat-x"

    def test_members_and_workspace_tokens_cannot_connect(self):
        for become in (self.as_member, self.as_workspace_token):
            become()
            r = self.send("post", f"{self.ws}/connections/", {"platform": "github", "access_token": "x"})
            assert r.status_code == 403, become.__name__

    def test_repositories_are_searched_and_marked_when_added(self):
        baker.make("app.Project", tenant=self.tenant, platform_connection=self.connection, external_id="101")

        r = self.get(f"{self.ws}/connections/{self.connection.id}/repositories/", q="auth")

        assert r.status_code == 200
        assert [(x["full_path"], x["already_added"]) for x in r.json()] == [("acme/auth-service", True)]

    def test_a_platform_failure_is_502(self):
        self.platform.return_value.search_projects.side_effect = RuntimeError("401")

        r = self.get(f"{self.ws}/connections/{self.connection.id}/repositories/")

        assert r.status_code == 502

    def test_another_workspaces_connection_is_404(self):
        other = baker.make("app.PlatformConnection")

        assert self.get(f"{self.ws}/connections/{other.id}/repositories/").status_code == 404


class TestProjects(ManageAPITestCase):
    def test_a_repository_is_added_by_path_with_its_standards_queued(self):
        r = self.send("post", f"{self.ws}/projects/", {
            "repository": "acme/auth-service", "standards": [str(self.readme.id)],
        })

        assert r.status_code == 201, r.content
        body = r.json()
        assert body["full_path"] == "acme/auth-service"
        assert body["webhook"] == "app"
        assert body["languages"] == ["Python"]
        assert [s["name"] for s in body["standards"]] == ["README Exists"]
        assert body["runs"]["queued"] == 1

    def test_nothing_is_attached_unless_listed(self):
        r = self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"})

        assert r.status_code == 201
        assert r.json()["standards"] == [] and r.json()["runs"] is None

    def test_adding_twice_is_409_and_an_unreachable_repo_is_404(self):
        self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"})

        assert self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"}).status_code == 409
        assert self.send("post", f"{self.ws}/projects/", {"repository": "acme/billing"}).status_code == 404

    def test_a_repo_two_connections_reach_needs_a_connection_id(self):
        second = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github",
            display_name="GitHub", auth_method=AuthMethod.PAT,
        )

        ambiguous = self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"})
        chosen = self.send("post", f"{self.ws}/projects/", {
            "repository": "acme/auth-service", "connection_id": str(second.id),
        })

        assert ambiguous.status_code == 400
        assert chosen.status_code == 201
        assert chosen.json()["webhook"] == "active"

    def test_a_workspace_token_can_add_projects(self):
        self.as_workspace_token()

        r = self.send("post", f"{self.ws}/projects/", {"repository": "acme/api-gateway"})

        assert r.status_code == 201

    def test_a_project_is_read_edited_and_removed(self):
        pid = self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"}).json()["id"]

        assert self.get(f"{self.ws}/projects/{pid}/").json()["lifecycle"] == "development"
        patched = self.send("patch", f"{self.ws}/projects/{pid}/", {"lifecycle": "production", "owner": "platform"})
        assert patched.status_code == 200
        assert (patched.json()["lifecycle"], patched.json()["owner"]) == ("production", "platform")
        assert self.send("patch", f"{self.ws}/projects/{pid}/", {"lifecycle": "someday"}).status_code == 400
        assert self.send("delete", f"{self.ws}/projects/{pid}/").status_code == 204
        assert not Project.objects.filter(pk=pid).exists()

    def test_standards_are_attached_and_detached(self):
        pid = self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"}).json()["id"]
        url = f"{self.ws}/projects/{pid}/standards/"

        attached = self.send("post", url, {"standards": [str(self.readme.id)]})
        again = self.send("post", url, {"standards": [str(self.readme.id)]})
        detached = self.send("delete", url, {"standards": [str(self.readme.id)]})

        assert attached.status_code == 200 and attached.json()["runs"]["queued"] == 1
        assert again.json()["runs"] is None
        assert detached.json() == {"standards": [], "runs": None}

    def test_another_workspaces_standard_cannot_be_attached(self):
        pid = self.send("post", f"{self.ws}/projects/", {"repository": "acme/auth-service"}).json()["id"]
        foreign = baker.make("app.Standard")

        r = self.send("post", f"{self.ws}/projects/{pid}/standards/", {"standards": [str(foreign.id)]})

        assert r.status_code == 404


class TestStandardOnOff(ManageAPITestCase):
    def test_turning_a_standard_off_and_on(self):
        off = self.send("post", f"{self.ws}/standards/{self.readme.id}/disable/")
        on = self.send("post", f"{self.ws}/standards/{self.readme.id}/enable/")

        assert off.status_code == 200 and off.json()["enabled"] is False
        assert on.status_code == 200 and on.json()["enabled"] is True

    def test_a_draft_cannot_be_turned_on(self):
        draft = baker.make("app.Standard", tenant=self.tenant, enabled=False, draft=True)

        r = self.send("post", f"{self.ws}/standards/{draft.id}/enable/")

        assert r.status_code == 400
        assert "draft" in r.json()["detail"]


class TestMarketplace(ManageAPITestCase):
    def setUp(self):
        super().setUp()
        self.mp_readme = baker.make(
            "app.MarketplaceStandard", slug="readme-exists", name="README Exists",
            code="def evaluate(project):\n    return {}\n", version=1, suggested_labels=["docs"],
        )
        self.mp_license = baker.make(
            "app.MarketplaceStandard", slug="license-file", name="License File",
            code="def evaluate(project):\n    return {}\n", version=1, suggested_labels=[],
        )
        self.pack = baker.make("app.MarketplacePack", slug="repo-hygiene", name="Repository Hygiene")
        self.pack.standards.set([self.mp_readme, self.mp_license])

    def test_browsing_shows_what_this_workspace_installed(self):
        self.send("post", f"{self.ws}/marketplace/standards/readme-exists/install/")

        r = self.get(f"{self.ws}/marketplace/")

        assert r.status_code == 200
        state = {x["slug"]: x["installed_standard_id"] is not None for x in r.json()["standards"]}
        assert state == {"readme-exists": True, "license-file": False}
        assert [p["slug"] for p in r.json()["packs"]] == ["repo-hygiene"]

    def test_a_pack_installs_what_is_missing(self):
        self.send("post", f"{self.ws}/marketplace/standards/readme-exists/install/")

        r = self.send("post", f"{self.ws}/marketplace/packs/repo-hygiene/install/")

        assert r.status_code == 200
        assert [x["name"] for x in r.json()["installed"]] == ["License File"]
        assert [x["name"] for x in r.json()["skipped"]] == ["README Exists"]
        assert Standard.objects.filter(tenant=self.tenant, source_marketplace_standard__isnull=False).count() == 2

    def test_installing_twice_returns_the_existing_copy(self):
        first = self.send("post", f"{self.ws}/marketplace/standards/readme-exists/install/").json()
        again = self.send("post", f"{self.ws}/marketplace/standards/readme-exists/install/").json()

        assert first["created"] is True and again["created"] is False
        assert first["id"] == again["id"]

    def test_an_installed_standard_is_updated_to_the_new_version(self):
        self.send("post", f"{self.ws}/marketplace/standards/readme-exists/install/")
        self.mp_readme.version = 2
        self.mp_readme.save()

        pack = self.get(f"{self.ws}/marketplace/packs/repo-hygiene/").json()
        assert {x["slug"]: x["update_available"] for x in pack["standards"]}["readme-exists"]
        r = self.send("post", f"{self.ws}/marketplace/standards/readme-exists/update/")

        assert r.status_code == 200 and r.json()["version"] == 2

    def test_unknown_slugs_are_404(self):
        assert self.get(f"{self.ws}/marketplace/packs/nope/").status_code == 404
        assert self.send("post", f"{self.ws}/marketplace/standards/nope/install/").status_code == 404
        assert self.send("post", f"{self.ws}/marketplace/standards/license-file/update/").status_code == 404
