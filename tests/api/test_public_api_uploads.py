"""Upload projects over the public API: how another system creates an upload
project and checks each build it uploads, with a workspace token."""
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker

from app.domain.models import APIToken, Platform, ProjectVersion
from tests.api.test_public_api import PublicAPITestCase
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

BUILD = make_zip({"dist/index.html": b"<html></html>", "dist/app.js": b"start()"})


class UploadAPITestCase(PublicAPITestCase):
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
        return self.send("post", f"{self.ws}/upload-projects/", body)

    def upload(self, project_id, data=BUILD, **fields):
        return self.client.post(
            f"{self.ws}/projects/{project_id}/versions/",
            {"archive": SimpleUploadedFile("build.zip", data), **fields},
            headers=self.auth,
        )


class TestCreateUploadProject(UploadAPITestCase):
    def test_creates_then_returns_the_same_project(self):
        first = self.create()
        assert first.status_code == 201
        body = first.json()
        assert body["platform"] == Platform.UPLOAD
        assert body["external_id"] == "ext-42"

        again = self.create()
        assert again.status_code == 200
        assert again.json()["id"] == body["id"]

    def test_a_name_is_required(self):
        assert self.create(name="").status_code == 400

    def test_an_unknown_standard_is_404(self):
        r = self.create(standard_ids=["00000000-0000-0000-0000-000000000000"])
        assert r.status_code == 404


class TestUploadVersion(UploadAPITestCase):
    def setUp(self):
        super().setUp()
        self.project_id = self.create().json()["id"]

    def test_an_upload_is_stored_and_queued(self):
        r = self.upload(self.project_id, label="1.0.0")

        assert r.status_code == 202, r.content
        body = r.json()
        assert body["created"] is True
        assert body["queued"] == 1
        version = body["version"]
        assert version["label"] == "1.0.0"
        assert version["channel"] == "main"
        assert version["file_count"] == 2
        assert version["uploaded_by"] == "ci-uploader"
        assert len(version["digest"]) == 40

    def test_the_check_is_polled_at_the_digest(self):
        digest = self.upload(self.project_id).json()["version"]["digest"]

        r = self.get(f"{self.ws}/projects/{self.project_id}/commits/{digest}/")

        assert r.status_code == 200
        assert r.json()["running"] == 1  # the worker has not run it yet

    def test_versions_are_listed_newest_first(self):
        self.upload(self.project_id, label="1.0")
        self.upload(self.project_id, data=make_zip({"x.js": b"x"}), label="1.1")

        r = self.get(f"{self.ws}/projects/{self.project_id}/versions/")

        assert [v["label"] for v in r.json()] == ["1.1", "1.0"]

    def test_a_rejected_archive_is_400_and_stores_nothing(self):
        r = self.upload(self.project_id, data=make_zip({"../../evil.js": b"x"}))
        assert r.status_code == 400
        assert "outside the archive" in r.json()["detail"]
        assert not ProjectVersion.objects.exists()

    def test_a_missing_archive_is_400(self):
        r = self.client.post(
            f"{self.ws}/projects/{self.project_id}/versions/", {}, headers=self.auth
        )
        assert r.status_code == 400

    def test_a_git_project_takes_no_uploads(self):
        git = baker.make("app.Project", tenant=self.tenant)
        assert self.upload(git.id).status_code == 404

    def test_another_workspace_cannot_upload(self):
        other = baker.make("app.Tenant")
        _, raw = APIToken.issue(name="x", created_by=self.user, tenant=other)
        r = self.client.post(
            f"/api/v1/workspaces/{other.id}/projects/{self.project_id}/versions/",
            {"archive": SimpleUploadedFile("build.zip", BUILD)},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 404
