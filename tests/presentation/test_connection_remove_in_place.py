"""Removing a connection on workspace settings answers over HTMX with the page
messages and a delete of that connection's row, and still redirects without JS."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import PlatformConnection

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
HX = {"HTTP_HX_REQUEST": "true"}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ConnectionRemoveInPlaceTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="admin")
        self.client.force_login(user)
        self.connection = baker.make(
            "app.PlatformConnection", tenant=self.tenant, display_name="My GitHub"
        )
        self.url = reverse("remove_connection", args=[self.connection.id])

    def test_htmx_remove_answers_with_the_message_and_deletes_the_row(self):
        response = self.client.post(self.url, **HX)

        assert response.status_code == 200
        body = response.content.decode()
        assert "<html" not in body
        assert 'id="flash-messages" hx-swap-oob="true"' in body
        assert "Connection &quot;My GitHub&quot; removed." in body
        assert (
            f'<template><tr id="conn-row-{self.connection.id}" hx-swap-oob="delete"></tr></template>'
            in body
        )
        assert not PlatformConnection.objects.filter(id=self.connection.id).exists()

    def test_without_htmx_it_still_redirects(self):
        response = self.client.post(self.url)

        self.assertRedirects(
            response, reverse("tenant_settings"), fetch_redirect_response=False
        )
        assert not PlatformConnection.objects.filter(id=self.connection.id).exists()
