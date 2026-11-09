"""Saving an LLM role on workspace settings answers in place over HTMX (the
role row only, messages out of band) and still redirects without JS."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import LLMRole

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
HX = {"HTTP_HX_REQUEST": "true"}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class LLMRoleInPlaceTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="admin")
        self.client.force_login(user)
        self.provider = baker.make(
            "app.LLMProvider",
            tenant=self.tenant,
            display_name="Claude",
            available_models=["opus", "sonnet"],
        )
        self.role = LLMRole.Name.values[0]
        self.url = reverse("set_llm_role", args=[self.role])

    def post(self, data, **headers):
        return self.client.post(self.url, data, **headers)

    def test_htmx_save_answers_with_the_role_row_and_the_message(self):
        response = self.post({"provider_id": self.provider.id, "model": "opus"}, **HX)

        assert response.status_code == 200
        body = response.content.decode()
        assert "<html" not in body
        assert 'data-current-model="opus"' in body
        assert 'id="flash-messages" hx-swap-oob="true"' in body
        assert "set to Claude/opus" in body
        assert LLMRole.objects.get(tenant=self.tenant, name=self.role).model == "opus"

    def test_htmx_error_shows_in_place_and_keeps_the_provider(self):
        response = self.post({"provider_id": self.provider.id, "model": ""}, **HX)

        assert response.status_code == 200
        body = response.content.decode()
        assert "Select a model for the role." in body
        assert f'value="{self.provider.id}" selected' in body
        assert not LLMRole.objects.filter(tenant=self.tenant).exists()

    def test_htmx_clear_answers_in_place(self):
        baker.make(
            "app.LLMRole", tenant=self.tenant, name=self.role, provider=self.provider, model="opus"
        )

        response = self.post({"provider_id": ""}, **HX)

        assert response.status_code == 200
        assert "Cleared" in response.content.decode()
        assert not LLMRole.objects.filter(tenant=self.tenant).exists()

    def test_without_js_it_redirects_to_settings(self):
        response = self.post({"provider_id": self.provider.id, "model": "opus"})

        assert response.status_code == 302
        assert response["Location"] == reverse("tenant_settings")

    def test_settings_page_draws_the_row_and_an_empty_message_area(self):
        body = self.client.get(reverse("tenant_settings")).content.decode()

        assert 'hx-target="this"' in body
        assert f'hx-post="{self.url}"' in body
        assert 'id="flash-messages">' in body
        assert "hx-swap-oob" not in body

    def test_htmx_non_admin_is_refused_in_place(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        self.client.force_login(member)

        response = self.post({"provider_id": self.provider.id, "model": "opus"}, **HX)

        assert response.status_code == 200
        assert response["HX-Reswap"] == "none"
        body = response.content.decode()
        assert 'id="flash-messages" hx-swap-oob="true"' in body
        assert "permission" in body
        assert "<form" not in body
        assert not LLMRole.objects.filter(tenant=self.tenant).exists()
