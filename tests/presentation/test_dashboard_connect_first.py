"""A workspace with no git platform can't add projects yet, so its admin's
dashboard leads with connecting one, linking straight to the open
Connections section of settings. Once connected, Add project leads again."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

CONNECT_URL = reverse("tenant_settings") + "#section-connections"


class DashboardConnectFirstTests(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make(
            "app.Membership", user=self.user, tenant=self.tenant, role="owner"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_admin_without_a_connection_is_led_to_connect_one(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Connect git platform")
        self.assertContains(response, f'href="{CONNECT_URL}" class="btn btn-sm btn-primary')
        self.assertContains(response, f'href="{CONNECT_URL}" class="link')

    def test_admin_with_a_connection_is_led_to_add_a_project(self):
        baker.make("app.PlatformConnection", tenant=self.tenant)

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Connect git platform")
        self.assertContains(
            response, f'href="{reverse("add_project_select")}" class="btn btn-sm btn-primary'
        )

    def test_member_who_cannot_connect_still_sees_add_project_first(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        self.client.force_login(member)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Connect git platform")
        self.assertContains(
            response, f'href="{reverse("add_project_select")}" class="btn btn-sm btn-primary'
        )
