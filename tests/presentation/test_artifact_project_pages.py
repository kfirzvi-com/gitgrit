"""Artifact projects in the web UI: creating one and uploading commits by
hand, browsing a commit's files from the Results tab, no Git-only controls, and the upload
connection never offered as something to edit, remove or import from."""
import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import artifact_service
from app.domain.models import CommitCheck, Project, ArtifactCommit
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
BUILD = make_zip({
    "dist/index.html": b"<html><script>alert(1)</script></html>",
    "dist/assets/app.js": b"start()",
    "dist/assets/logo.png": PNG,
    "dist/assets/icon.svg": b"<svg onload='alert(1)'/>",
})


class UploadPageTestCase(TestCase):
    def setUp(self):
        self.user = baker.make("app.User", username="kfir")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.standard = baker.make("app.Standard", tenant=self.tenant, criteria={"events": ["push"]})
        self.project = artifact_service.create_artifact_project(
            self.tenant, name="Storefront", external_id="ext-42", standard_ids=[str(self.standard.pk)]
        ).project
        patch = defer_patch()
        self.configure = patch.start()
        self.addCleanup(patch.stop)

    def page(self, project=None):
        project = project or self.project
        return self.client.get(reverse("project_detail", args=[project.pk])).content.decode()

    def upload(self, data=BUILD, **fields):
        return self.client.post(
            reverse("upload_project_commit", args=[self.project.pk]),
            {"archive": SimpleUploadedFile("build.zip", data), **fields},
            headers={"HX-Request": "true"},
        )


class ProjectPageTests(UploadPageTestCase):
    def test_the_project_page_offers_no_webhook_or_repository_link(self):
        page = self.page()
        self.assertNotIn("Register now", page)
        self.assertNotIn("Open in Upload", page)
        self.assertIn("Default branch", page)

    def test_registering_a_webhook_is_refused(self):
        resp = self.client.post(reverse("retry_webhook", args=[self.project.pk]))
        self.assertRedirects(resp, reverse("project_detail", args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.webhook_id, "")

    def test_an_upload_project_has_an_upload_button_and_no_files_tab(self):
        page = self.page()
        self.assertIn("data-upload-commit", page)
        self.assertIn('id="commit_files_modal"', page)
        self.assertNotIn('data-tab="files"', page)

    def test_a_git_project_has_neither(self):
        page = self.page(baker.make("app.Project", tenant=self.tenant))
        self.assertNotIn("data-upload-commit", page)
        self.assertNotIn('id="commit_files_modal"', page)


class EmptyProjectTests(UploadPageTestCase):
    """Before the first upload there is nothing to run the standards on."""

    def test_the_overview_asks_for_an_upload_not_a_run(self):
        page = self.page()
        self.assertIn("No commits uploaded yet", page)
        self.assertNotIn("Run the standards", page)

    def test_the_results_tab_offers_an_upload_instead_of_a_run(self):
        page = self.client.get(reverse("project_history", args=[self.project.pk])).content.decode()
        self.assertNotIn("Run on latest", page)
        self.assertIn("Upload a commit", page)
        self.assertIn("No commits uploaded to main yet", page)

    def test_running_on_an_empty_branch_queues_nothing(self):
        resp = self.client.post(reverse("run_on_branch", args=[self.project.pk]), {"branch": "main"})
        self.assertIn("No commit has been uploaded to main yet", resp.content.decode())
        self.assertFalse(CommitCheck.objects.exists())
        self.configure.assert_not_called()


class UploadCommitTests(UploadPageTestCase):
    def test_an_upload_is_stored_queued_and_announced(self):
        resp = self.upload(message="Release 1.0.0", branch="review")

        commit = ArtifactCommit.objects.get()
        self.assertEqual(commit.message, "Release 1.0.0")
        self.assertEqual(commit.branch, "review")
        self.assertEqual(commit.author, "kfir")
        self.assertEqual(commit.author_user, self.user)
        self.assertEqual(CommitCheck.objects.get().commit_sha, commit.sha)
        triggers = json.loads(resp["HX-Trigger"])
        self.assertEqual(triggers["commitUploaded"]["sha"], commit.sha)
        self.assertIn(f"Uploaded {commit.sha[:7]}", triggers["toast"]["text"])

    def test_a_rejected_archive_shows_why_and_stores_nothing(self):
        resp = self.upload(make_zip({"../evil.js": b"x"}), message="Release 1.0.0")
        body = resp.content.decode()
        self.assertIn("data-upload-error", body)
        self.assertIn("outside the archive", body)
        self.assertIn("Release 1.0.0</textarea>", body)  # what was typed is kept
        self.assertNotIn("HX-Trigger", resp)
        self.assertFalse(ArtifactCommit.objects.exists())

    def test_without_an_archive_it_asks_for_one(self):
        resp = self.client.post(reverse("upload_project_commit", args=[self.project.pk]), {})
        self.assertIn("Choose a .zip or .tar.gz", resp.content.decode())

    def test_a_git_project_takes_no_uploads(self):
        git = baker.make("app.Project", tenant=self.tenant)
        resp = self.client.post(
            reverse("upload_project_commit", args=[git.pk]),
            {"archive": SimpleUploadedFile("build.zip", BUILD)},
        )
        self.assertEqual(resp.status_code, 404)


class AddUploadProjectTests(UploadPageTestCase):
    def test_the_add_page_offers_an_upload_but_not_the_upload_connection(self):
        page = self.client.get(reverse("add_project_select")).content.decode()
        self.assertIn("data-add-artifact-project", page)
        self.assertNotIn(artifact_service.ARTIFACT_CONNECTION_NAME, page)

    def test_creating_with_a_first_commit(self):
        resp = self.client.post(reverse("add_artifact_project"), {
            "name": "Checkout", "stack": "Web Team", "message": "First release",
            "archive": SimpleUploadedFile("checkout.zip", BUILD),
        })

        project = Project.objects.get(name="Checkout")
        self.assertTrue(project.is_artifact)
        self.assertEqual(project.root_component.stacks.get().name, "Web Team")
        self.assertEqual(project.artifact_commits.get().message, "First release")
        self.assertRedirects(
            resp, reverse("project_detail", args=[project.pk]) + "#results",
            fetch_redirect_response=False,
        )

    def test_creating_without_an_archive(self):
        self.client.post(reverse("add_artifact_project"), {"name": "Checkout"})
        project = Project.objects.get(name="Checkout")
        self.assertFalse(project.artifact_commits.exists())

    def test_two_projects_of_the_same_name_stay_apart(self):
        self.client.post(reverse("add_artifact_project"), {"name": "Checkout"})
        self.client.post(reverse("add_artifact_project"), {"name": "Checkout"})
        self.assertEqual(Project.objects.filter(name="Checkout").count(), 2)

    def test_a_name_is_required(self):
        resp = self.client.post(reverse("add_artifact_project"), {"name": " "})
        self.assertIn("Give the project a name", resp.content.decode())
        self.assertFalse(Project.objects.filter(name="").exists())


class SettingsTests(UploadPageTestCase):
    def test_settings_do_not_list_the_upload_connection(self):
        baker.make("app.PlatformConnection", tenant=self.tenant, display_name="Acme GitHub")
        page = self.client.get(reverse("tenant_settings")).content.decode()
        self.assertIn("Acme GitHub", page)
        self.assertNotIn(artifact_service.ARTIFACT_CONNECTION_NAME, page)


class CommitFilesTests(UploadPageTestCase):
    """A commit's files, in the modal its SHA opens from the Results tab."""

    def setUp(self):
        super().setUp()
        self.upload(message="Release 1.0.0")
        self.commit = ArtifactCommit.objects.get()
        self.url = reverse("commit_files", args=[self.project.pk])
        self.raw_url = reverse("commit_file_raw", args=[self.project.pk])

    def test_the_sha_in_the_results_tab_opens_the_files(self):
        page = self.client.get(reverse("project_history", args=[self.project.pk])).content.decode()
        self.assertIn(f'data-commit-files-url="{self.url}?sha={self.commit.sha}"', page)

    def test_a_git_project_sha_does_not(self):
        git = baker.make("app.Project", tenant=self.tenant)
        with mock.patch("app.application.commit_checks._client") as client:
            client.return_value.list_branches.return_value = ["main"]
            client.return_value.list_commits.return_value = [
                {"sha": "a" * 40, "message": "x", "author": "", "date": "", "url": ""}
            ]
            page = self.client.get(reverse("project_history", args=[git.pk])).content.decode()
        self.assertNotIn("data-commit-files-url", page)

    def test_the_tree_shows_the_files_without_the_wrapping_folder(self):
        page = self.client.get(self.url, {"sha": self.commit.sha}).content.decode()
        for path in ("index.html", "assets/app.js", "assets/logo.png"):
            self.assertIn(f'data-file="{path}"', page)
        self.assertNotIn('data-folder="dist"', page)
        self.assertIn("4 files", page)
        self.assertIn("Release 1.0.0", page)

    def test_an_unknown_sha_is_404(self):
        self.assertEqual(self.client.get(self.url, {"sha": "f" * 40}).status_code, 404)

    def test_a_text_file_is_shown_escaped(self):
        resp = self.client.get(
            self.url, {"sha": self.commit.sha, "path": "index.html"},
            headers={"HX-Request": "true", "HX-Target": "file-view"},
        )
        body = resp.content.decode()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)", body)
        self.assertNotIn("data-file-tree", body)  # just the viewer

    def test_an_image_is_previewed_through_the_raw_endpoint(self):
        page = self.client.get(self.url, {"sha": self.commit.sha, "path": "assets/logo.png"}).content.decode()
        self.assertIn(self.raw_url, page)

        raw = self.client.get(self.raw_url, {"sha": self.commit.sha, "path": "assets/logo.png"})
        self.assertEqual(raw["Content-Type"], "image/png")
        self.assertEqual(raw["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", raw["Content-Security-Policy"])
        self.assertEqual(raw.content, PNG)

    def test_markup_and_svg_are_never_served_raw(self):
        for path in ("index.html", "assets/icon.svg", "assets/app.js"):
            with self.subTest(path=path):
                resp = self.client.get(self.raw_url, {"sha": self.commit.sha, "path": path})
                self.assertEqual(resp.status_code, 404)

    def test_a_missing_file_says_so(self):
        page = self.client.get(self.url, {"sha": self.commit.sha, "path": "nope.js"}).content.decode()
        self.assertIn("This commit has no such file", page)

    def test_another_workspace_cannot_browse(self):
        other = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=other, tenant=tenant, role="owner")
        self.client.force_login(other)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.assertEqual(self.client.get(self.url, {"sha": self.commit.sha}).status_code, 404)


class CommitDownloadTests(UploadPageTestCase):
    def setUp(self):
        super().setUp()
        self.upload(message="Release 1.0.0")
        self.commit = ArtifactCommit.objects.get()
        self.url = reverse("commit_download", args=[self.project.pk])

    def test_the_whole_archive_downloads_as_uploaded(self):
        resp = self.client.get(self.url, {"sha": self.commit.sha})
        self.assertEqual(resp.content, BUILD)
        self.assertEqual(
            resp["Content-Disposition"], f'attachment; filename="storefront-{self.commit.sha[:7]}.zip"'
        )
        self.assertEqual(resp["Content-Type"], "application/octet-stream")

    def test_one_file_downloads_as_an_attachment_never_a_page(self):
        resp = self.client.get(self.url, {"sha": self.commit.sha, "path": "index.html"})
        self.assertEqual(resp.content, b"<html><script>alert(1)</script></html>")
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="index.html"')
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", resp["Content-Security-Policy"])

    def test_the_files_view_offers_both_downloads(self):
        files_url = reverse("commit_files", args=[self.project.pk])
        page = self.client.get(files_url, {"sha": self.commit.sha, "path": "index.html"}).content.decode()
        self.assertIn("data-download-archive", page)
        self.assertIn("data-download-file", page)

    def test_a_missing_file_or_commit_is_404(self):
        self.assertEqual(self.client.get(self.url, {"sha": self.commit.sha, "path": "nope"}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {"sha": "f" * 40}).status_code, 404)

    def test_another_workspace_cannot_download(self):
        other = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=other, tenant=tenant, role="owner")
        self.client.force_login(other)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.assertEqual(self.client.get(self.url, {"sha": self.commit.sha}).status_code, 404)
