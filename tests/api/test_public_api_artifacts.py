"""Artifact projects over the public API: how another system creates an upload
project and checks each build it uploads, with a workspace token."""
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker

from app.domain.models import APIToken, Platform, ArtifactCommit
from tests.api.test_public_api import PublicAPITestCase
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

BUILD = make_zip({"dist/index.html": b"<html></html>", "dist/app.js": b"start()"})


class ArtifactAPITestCase(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        _, raw = APIToken.issue(name="ci-uploader", created_by=self.user, tenant=self.tenant)
        self.auth = {"Authorization": f"Bearer {raw}"}
        self.standard = baker.make(
            "app.Standard", tenant=self.tenant, name="No source maps",
            criteria={"events": ["upload"]},
        )
        patch = defer_patch()
        self.configure = patch.start()
        self.addCleanup(patch.stop)

    def create(self, **body):
        body = {"name": "Storefront", "external_id": "ext-42", "stack": "Acme Web", **body}
        return self.send("post", f"{self.ws}/projects/", {"type": "artifact", **body})

    def upload(self, project_id, data=BUILD, **fields):
        return self.client.post(
            f"{self.ws}/projects/{project_id}/commits/",
            {"archive": SimpleUploadedFile("build.zip", data), **fields},
            headers=self.auth,
        )


class TestCreateArtifactProject(ArtifactAPITestCase):
    def test_creates_then_returns_the_same_project(self):
        first = self.create()
        assert first.status_code == 201
        body = first.json()
        assert body["platform"] == Platform.ARTIFACT
        assert body["external_id"] == "ext-42"

        again = self.create()
        assert again.status_code == 200
        assert again.json()["id"] == body["id"]

    def test_only_artifact_projects_are_created_here(self):
        assert self.create(type="github").status_code == 400

    def test_a_name_is_required(self):
        assert self.create(name="").status_code == 400

    def test_an_unknown_standard_is_404(self):
        r = self.create(standard_ids=["00000000-0000-0000-0000-000000000000"])
        assert r.status_code == 404


class TestUploadCommit(ArtifactAPITestCase):
    def setUp(self):
        super().setUp()
        self.project_id = self.create().json()["id"]

    def test_an_upload_is_stored_and_queued(self):
        r = self.upload(self.project_id, message="Release 1.0.0")

        assert r.status_code == 202, r.content
        body = r.json()
        assert body["created"] is True
        assert body["queued"] == 1
        commit = body["commit"]
        assert commit["message"] == "Release 1.0.0"
        assert commit["branch"] == "main"
        assert commit["file_count"] == 2
        assert commit["author"] == "ci-uploader"
        assert len(commit["sha"]) == 40

    def test_the_check_is_polled_at_the_sha(self):
        sha = self.upload(self.project_id).json()["commit"]["sha"]

        r = self.get(f"{self.ws}/projects/{self.project_id}/commits/{sha}/")

        assert r.status_code == 200
        assert r.json()["running"] == 1  # the worker has not run it yet

    def test_uploads_are_listed_as_the_branch_commits(self):
        self.upload(self.project_id, message="Release 1.0")
        self.upload(self.project_id, data=make_zip({"x.js": b"x"}), message="Release 1.1\n\nnotes")

        r = self.get(f"{self.ws}/projects/{self.project_id}/commits/", branch="main")

        assert r.status_code == 200
        assert [c["title"] for c in r.json()["commits"]] == ["Release 1.1", "Release 1.0"]

    def test_a_rejected_archive_is_400_and_stores_nothing(self):
        r = self.upload(self.project_id, data=make_zip({"../../evil.js": b"x"}))
        assert r.status_code == 400
        assert "outside the archive" in r.json()["detail"]
        assert not ArtifactCommit.objects.exists()

    def test_a_missing_archive_is_400(self):
        r = self.client.post(
            f"{self.ws}/projects/{self.project_id}/commits/", {}, headers=self.auth
        )
        assert r.status_code == 400

    def test_a_git_project_takes_no_uploads(self):
        git = baker.make("app.Project", tenant=self.tenant)
        assert self.upload(git.id).status_code == 404

    def test_another_workspace_cannot_upload(self):
        other = baker.make("app.Tenant")
        _, raw = APIToken.issue(name="x", created_by=self.user, tenant=other)
        r = self.client.post(
            f"/api/v1/workspaces/{other.id}/projects/{self.project_id}/commits/",
            {"archive": SimpleUploadedFile("build.zip", BUILD)},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 404
