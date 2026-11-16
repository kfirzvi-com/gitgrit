"""The bulk bars' endpoints: they answer with a toast and ask the page to
fetch its table again; nothing changes without a selection."""
import json

from django.test import TestCase
from django.urls import reverse
from model_bakery import baker


class BulkEditViewTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _triggers(self, response):
        return json.loads(response["HX-Trigger"])

    def test_disabling_standards_toasts_and_reloads_the_table(self):
        standard = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)

        response = self.client.post(reverse("bulk_edit_standards"), {"action": "disable", "ids": [standard.pk]})

        triggers = self._triggers(response)
        assert triggers["toast"]["text"] == "Disabled 1 standard."
        assert triggers["smart-table:reload"] is True
        standard.refresh_from_db()
        assert not standard.enabled

    def test_setting_projects_lifecycle(self):
        project = baker.make("app.Project", tenant=self.tenant, lifecycle="development")

        response = self.client.post(
            reverse("bulk_edit_projects"), {"action": "set_lifecycle", "value": "staging", "ids": [project.pk]}
        )

        assert self._triggers(response)["toast"]["level"] == "success"
        project.refresh_from_db()
        assert project.lifecycle == "staging"

    def test_nothing_selected_is_a_warning_and_no_reload(self):
        response = self.client.post(reverse("bulk_edit_projects"), {"action": "set_lifecycle", "value": "staging"})

        triggers = self._triggers(response)
        assert triggers["toast"]["level"] == "warning"
        assert "smart-table:reload" not in triggers

    def test_a_bad_value_is_an_error_toast(self):
        project = baker.make("app.Project", tenant=self.tenant)

        response = self.client.post(
            reverse("bulk_edit_projects"), {"action": "set_lifecycle", "value": "retired", "ids": [project.pk]}
        )

        assert self._triggers(response)["toast"]["level"] == "error"

    def test_the_pages_offer_the_bulk_bar(self):
        baker.make("app.Project", tenant=self.tenant)
        baker.make("app.Standard", tenant=self.tenant)

        for name in ("project_list", "standard_list"):
            body = self.client.get(reverse(name)).content.decode()
            assert "data-bulk-bar" in body and "data-row-select" in body
