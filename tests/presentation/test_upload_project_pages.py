"""Upload projects in the web UI: creating one and uploading versions by
hand, browsing a version's files, no Git-only controls, and the upload
connection never offered as something to edit, remove or import from."""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import upload_service
from app.domain.models import CommitCheck, Project, ProjectVersion
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
GAME = make_zip({
    "dist/index.html": b"<html><script>alert(1)</script></html>",
    "dist/assets/game.js": b"start()",
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
        self.standard = baker.make("app.Standard", tenant=self.tenant, criteria={"events": ["upload"]})
        self.project = upload_service.create_upload_project(
            self.tenant, name="Space Race", external_id="game-42"
        ).project
        patch = defer_patch()
        self.configure = patch.start()
        self.addCleanup(patch.stop)

    def page(self, project=None):
        project = project or self.project
        return self.client.get(reverse("project_detail", args=[project.pk])).content.decode()

    def upload(self, data=GAME, **fields):
        return self.client.post(
            reverse("upload_project_version", args=[self.project.pk]),
            {"archive": SimpleUploadedFile("game.zip", data), **fields},
            headers={"HX-Request": "true"},
        )


class ProjectPageTests(UploadPageTestCase):
    def test_the_project_page_offers_no_webhook_or_repository_link(self):
        page = self.page()
        self.assertNotIn("Register now", page)
        self.assertNotIn("Open in Upload", page)
        self.assertIn("Default channel", page)

    def test_registering_a_webhook_is_refused(self):
        resp = self.client.post(reverse("retry_webhook", args=[self.project.pk]))
        self.assertRedirects(resp, reverse("project_detail", args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.webhook_id, "")

    def test_an_upload_project_has_an_upload_button_and_a_files_tab(self):
        page = self.page()
        self.assertIn("data-upload-version", page)
        self.assertIn('data-tab="files"', page)

    def test_a_git_project_has_neither(self):
        page = self.page(baker.make("app.Project", tenant=self.tenant))
        self.assertNotIn("data-upload-version", page)
        self.assertNotIn('data-tab="files"', page)


class EmptyProjectTests(UploadPageTestCase):
    """Before the first upload there is nothing to run the standards on."""

    def test_the_overview_asks_for_an_upload_not_a_run(self):
        page = self.page()
        self.assertIn("No versions uploaded yet", page)
        self.assertNotIn("Run the standards", page)

    def test_the_results_tab_offers_an_upload_instead_of_a_run(self):
        page = self.client.get(reverse("project_history", args=[self.project.pk])).content.decode()
        self.assertNotIn("Run on latest", page)
        self.assertIn("Upload a version", page)
        self.assertIn("No versions uploaded to main yet", page)

    def test_running_on_an_empty_channel_queues_nothing(self):
        resp = self.client.post(reverse("run_on_branch", args=[self.project.pk]), {"branch": "main"})
        self.assertIn("No version has been uploaded to main yet", resp.content.decode())
        self.assertFalse(CommitCheck.objects.exists())
        self.configure.assert_not_called()


class UploadVersionTests(UploadPageTestCase):
    def test_an_upload_is_stored_queued_and_announced(self):
        resp = self.upload(label="1.0.0")

        version = ProjectVersion.objects.get()
        self.assertEqual(version.label, "1.0.0")
        self.assertEqual(version.uploaded_by, "kfir")
        self.assertEqual(version.uploaded_by_user, self.user)
        self.assertEqual(CommitCheck.objects.get().commit_sha, version.digest)
        triggers = json.loads(resp["HX-Trigger"])
        self.assertEqual(triggers["versionUploaded"]["digest"], version.digest)
        self.assertIn("Uploaded 1.0.0", triggers["toast"]["text"])

    def test_a_rejected_archive_shows_why_and_stores_nothing(self):
        resp = self.upload(make_zip({"../evil.js": b"x"}), label="1.0.0")
        body = resp.content.decode()
        self.assertIn("data-upload-error", body)
        self.assertIn("outside the archive", body)
        self.assertIn('value="1.0.0"', body)  # what was typed is kept
        self.assertNotIn("HX-Trigger", resp)
        self.assertFalse(ProjectVersion.objects.exists())

    def test_without_an_archive_it_asks_for_one(self):
        resp = self.client.post(reverse("upload_project_version", args=[self.project.pk]), {})
        self.assertIn("Choose a .zip or .tar.gz", resp.content.decode())

    def test_a_git_project_takes_no_uploads(self):
        git = baker.make("app.Project", tenant=self.tenant)
        resp = self.client.post(
            reverse("upload_project_version", args=[git.pk]),
            {"archive": SimpleUploadedFile("game.zip", GAME)},
        )
        self.assertEqual(resp.status_code, 404)


class AddUploadProjectTests(UploadPageTestCase):
    def test_the_add_page_offers_an_upload_but_not_the_upload_connection(self):
        page = self.client.get(reverse("add_project_select")).content.decode()
        self.assertIn("data-add-upload-project", page)
        self.assertNotIn(upload_service.UPLOAD_CONNECTION_NAME, page)

    def test_creating_with_a_first_version(self):
        resp = self.client.post(reverse("add_upload_project"), {
            "name": "Moon Dash", "stack": "Nebula Games", "label": "0.1.0",
            "archive": SimpleUploadedFile("moon.zip", GAME),
        })

        project = Project.objects.get(name="Moon Dash")
        self.assertTrue(project.is_upload)
        self.assertEqual(project.root_component.stacks.get().name, "Nebula Games")
        self.assertEqual(project.versions.get().label, "0.1.0")
        self.assertRedirects(
            resp, reverse("project_detail", args=[project.pk]) + "#results",
            fetch_redirect_response=False,
        )

    def test_creating_without_an_archive(self):
        self.client.post(reverse("add_upload_project"), {"name": "Moon Dash"})
        project = Project.objects.get(name="Moon Dash")
        self.assertFalse(project.versions.exists())

    def test_two_projects_of_the_same_name_stay_apart(self):
        self.client.post(reverse("add_upload_project"), {"name": "Moon Dash"})
        self.client.post(reverse("add_upload_project"), {"name": "Moon Dash"})
        self.assertEqual(Project.objects.filter(name="Moon Dash").count(), 2)

    def test_a_name_is_required(self):
        resp = self.client.post(reverse("add_upload_project"), {"name": " "})
        self.assertIn("Give the project a name", resp.content.decode())
        self.assertFalse(Project.objects.filter(name="").exists())


class SettingsTests(UploadPageTestCase):
    def test_settings_do_not_list_the_upload_connection(self):
        baker.make("app.PlatformConnection", tenant=self.tenant, display_name="Acme GitHub")
        page = self.client.get(reverse("tenant_settings")).content.decode()
        self.assertIn("Acme GitHub", page)
        self.assertNotIn(upload_service.UPLOAD_CONNECTION_NAME, page)


class FilesTabTests(UploadPageTestCase):
    def setUp(self):
        super().setUp()
        self.upload(label="1.0.0")
        self.version = ProjectVersion.objects.get()
        self.url = reverse("project_files", args=[self.project.pk])

    def test_the_tree_shows_the_files_without_the_wrapping_folder(self):
        page = self.client.get(self.url).content.decode()
        for path in ("index.html", "assets/game.js", "assets/logo.png"):
            self.assertIn(f'data-file="{path}"', page)
        self.assertNotIn('data-folder="dist"', page)
        self.assertIn("4 files", page)

    def test_a_text_file_is_shown_escaped(self):
        resp = self.client.get(
            self.url, {"version": self.version.digest, "path": "index.html"},
            headers={"HX-Request": "true", "HX-Target": "file-view"},
        )
        body = resp.content.decode()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)", body)
        self.assertNotIn("data-file-tree", body)  # just the viewer

    def test_an_image_is_previewed_through_the_raw_endpoint(self):
        page = self.client.get(self.url, {"path": "assets/logo.png"}).content.decode()
        self.assertIn(reverse("project_file_raw", args=[self.project.pk]), page)

        raw = self.client.get(
            reverse("project_file_raw", args=[self.project.pk]),
            {"version": self.version.digest, "path": "assets/logo.png"},
        )
        self.assertEqual(raw["Content-Type"], "image/png")
        self.assertEqual(raw["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", raw["Content-Security-Policy"])
        self.assertEqual(raw.content, PNG)

    def test_markup_and_svg_are_never_served_raw(self):
        raw_url = reverse("project_file_raw", args=[self.project.pk])
        for path in ("index.html", "assets/icon.svg", "assets/game.js"):
            with self.subTest(path=path):
                resp = self.client.get(raw_url, {"version": self.version.digest, "path": path})
                self.assertEqual(resp.status_code, 404)

    def test_a_missing_file_says_so(self):
        page = self.client.get(self.url, {"path": "nope.js"}).content.decode()
        self.assertIn("This version has no such file", page)

    def test_another_workspace_cannot_browse(self):
        other = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=other, tenant=tenant, role="owner")
        self.client.force_login(other)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
