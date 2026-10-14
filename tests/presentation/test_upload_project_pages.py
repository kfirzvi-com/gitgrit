"""Upload projects in the web UI: no Git-only controls, and the upload
connection is never offered as something to edit, remove or import from."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import upload_service
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch


class UploadProjectPagesTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = upload_service.create_upload_project(
            self.tenant, name="Space Race", external_id="game-42"
        ).project
        with defer_patch():
            upload_service.upload_version(self.project, make_zip({"index.html": b"<html/>"}))

    def test_the_project_page_offers_no_webhook_or_repository_link(self):
        page = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()
        self.assertNotIn("Register now", page)
        self.assertNotIn("Open in Upload", page)
        self.assertIn("Default channel", page)
        self.assertIn("1 uploaded", page)

    def test_registering_a_webhook_is_refused(self):
        resp = self.client.post(reverse("retry_webhook", args=[self.project.pk]))
        self.assertRedirects(resp, reverse("project_detail", args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.webhook_id, "")

    def test_settings_do_not_list_the_upload_connection(self):
        baker.make("app.PlatformConnection", tenant=self.tenant, display_name="Acme GitHub")
        page = self.client.get(reverse("tenant_settings")).content.decode()
        self.assertIn("Acme GitHub", page)
        self.assertNotIn(upload_service.UPLOAD_CONNECTION_NAME, page)

    def test_adding_a_project_does_not_offer_the_upload_connection(self):
        resp = self.client.get(reverse("add_project_select"))
        # Only the upload connection exists: there is nothing to import from.
        self.assertRedirects(resp, reverse("tenant_settings"), fetch_redirect_response=False)
