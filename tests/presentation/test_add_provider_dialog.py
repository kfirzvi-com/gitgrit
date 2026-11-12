"""Adding an LLM provider: a button in the providers card that opens a dialog."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class AddProviderButtonTests(TestCase):
    """Adding a provider is a button in the providers card that opens a dialog,
    not a form always open on the page."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def _page(self, role):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        return self.client.get(reverse("tenant_settings")).content.decode()

    def test_an_admin_gets_the_button_and_the_dialog(self):
        body = self._page("admin")

        self.assertIn("data-open-add-provider", body)  # in the empty state
        dialog = body.split('id="add-provider-modal"', 1)[1]
        self.assertIn(f'action="{reverse("add_llm_provider")}"', dialog)
        self.assertNotIn("Add LLM Provider</h2>", body)

    def test_a_member_does_not(self):
        body = self._page("member")

        self.assertNotIn("data-open-add-provider", body)
        self.assertNotIn('id="add-provider-modal"', body)
