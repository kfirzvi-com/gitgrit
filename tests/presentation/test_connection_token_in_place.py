"""Updating a connection's token on workspace settings answers over HTMX with
the page messages only (the dialog closes itself) and still redirects without JS."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
HX = {"HTTP_HX_REQUEST": "true"}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ConnectionTokenInPlaceTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="admin")
        self.client.force_login(user)
        self.connection = baker.make(
            "app.PlatformConnection",
            tenant=self.tenant,
            display_name="My GitHub",
            access_token="old-token",
        )
        self.url = reverse("edit_connection_token", args=[self.connection.id])

    def test_htmx_save_stores_the_token_and_answers_with_the_message_only(self):
        response = self.client.post(self.url, {"access_token": "new-token"}, **HX)

        assert response.status_code == 200
        body = response.content.decode()
        assert "<html" not in body
        assert 'id="flash-messages" hx-swap-oob="true"' in body
        assert "Token updated for &quot;My GitHub&quot;." in body
        self.connection.refresh_from_db()
        assert self.connection.access_token == "new-token"

    def test_htmx_blank_token_answers_with_the_error(self):
        response = self.client.post(self.url, {"access_token": " "}, **HX)

        assert response.status_code == 200
        assert "Access token is required." in response.content.decode()
        self.connection.refresh_from_db()
        assert self.connection.access_token == "old-token"

    def test_without_htmx_it_still_redirects(self):
        response = self.client.post(self.url, {"access_token": "new-token"})

        self.assertRedirects(
            response, reverse("tenant_settings"), fetch_redirect_response=False
        )
