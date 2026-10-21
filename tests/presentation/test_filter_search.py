"""The GitHub-like filter search on a project's Standards tab and on the
Standards page: which fields each offers, and that every row says the
values the search filters on (data-filter-*)."""
import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.presentation.filter_search import StandardListFilterSearch, StandardPickerFilterSearch

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _config(body):
    """The filter search's config, as the page's script reads it."""
    match = re.search(r'data-filter-search>\s*<script type="application/json">(.*?)</script>', body, re.S)
    return json.loads(match.group(1))


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class StandardFilterSearchTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        security = baker.make("app.StandardLabel", tenant=self.tenant, name="Security")
        quality = baker.make("app.StandardLabel", tenant=self.tenant, name="Code quality")
        self.secrets = baker.make(
            "app.Standard", tenant=self.tenant, name="No Secrets", description="Finds keys", enabled=True, draft=False,
        )
        self.secrets.labels.add(security, quality)
        self.linter = baker.make(
            "app.Standard", tenant=self.tenant, name="Linter", description="", enabled=False, draft=True,
        )
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.project.standards.add(self.secrets)

    def test_the_picker_filters_by_attached_importance_label_name_and_description(self):
        search = StandardPickerFilterSearch.for_standards([self.secrets, self.linter])

        assert [f.key for f in search.fields] == ["is", "importance", "label", "name", "description"]
        assert [f.key for f in search.menu_fields] == ["is", "importance", "label"]
        label = search.fields[2]
        assert [(v.value, v.label) for v in label.values] == [("code quality", "Code quality"), ("security", "Security")]

    def test_the_standards_page_filters_by_status_label_name_and_description(self):
        search = StandardListFilterSearch.for_standards([self.secrets, self.linter])

        assert [f.key for f in search.fields] == ["is", "label", "name", "description"]
        assert [v.value for v in search.fields[0].values] == ["enabled", "disabled", "draft"]
        assert StandardListFilterSearch.statuses_of(self.linter) == ["disabled", "draft"]

    def test_the_standards_tab_rows_say_their_labels_name_and_description(self):
        body = self.client.get(
            reverse("project_standards", args=[self.project.pk]) + "?embed=tab", HTTP_HX_REQUEST="true"
        ).content.decode()

        assert [f["key"] for f in _config(body)["fields"]] == ["is", "importance", "label", "name", "description"]
        assert 'data-filter-label="security|code quality"' in body or 'data-filter-label="code quality|security"' in body
        assert 'data-filter-name="no secrets"' in body
        assert 'data-filter-description="finds keys"' in body
        assert 'data-filter-toggle="label" data-filter-value="security"' in body
        assert ">Labels</button>" in body
        assert "data-filter-empty" in body

    def test_the_standards_page_rows_say_their_status(self):
        body = self.client.get(reverse("standard_list")).content.decode()

        assert [f["key"] for f in _config(body)["fields"]] == ["is", "label", "name", "description"]
        assert 'data-filter-is="enabled"' in body
        assert 'data-filter-is="disabled|draft"' in body
