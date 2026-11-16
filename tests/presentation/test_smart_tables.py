"""The Projects and Stacks pages as smart tables: the filter search's fields,
the sorts and groupings each table offers, and that every row says what it
is filtered, sorted and grouped by (data-filter-*, data-sort-*, data-group-*)."""
import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.presentation.filter_search import ProjectListFilterSearch, StackListFilterSearch
from app.presentation.smart_table import (
    ProjectListSmartTable,
    ProjectRow,
    StackListSmartTable,
    StackRow,
    StandardListSmartTable,
    StandardRow,
)

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _smart_table_config(body):
    match = re.search(r'<div data-smart-table>\s*<script type="application/json">(.*?)</script>', body, re.S)
    return json.loads(match.group(1))


class Fixture(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.orders = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        self.platform = baker.make("app.Stack", tenant=self.tenant, name="Platform")
        self.api = self._project("api", owner="Payments team", lifecycle="production", languages=["Python"])
        self.infra = self._project("infra", owner="Platform team", lifecycle="staging", languages=["HCL"])
        self.lonely = self._project("lonely", owner="", lifecycle="development")
        # Every project gets its root component when created.
        self.api.root_component.stacks.add(self.orders, self.platform)
        self.infra.root_component.stacks.add(self.platform)

    def _project(self, name, **fields):
        return baker.make("app.Project", tenant=self.tenant, name=name, full_path=f"acme/{name}", **fields)


class ProjectRowTests(Fixture):
    def test_a_row_lists_its_stacks_once_each_a_to_z(self):
        rows = {r.project.name: r for r in ProjectRow.for_projects(self.tenant.projects.prefetch_related("components__stacks"))}

        assert [s.name for s in rows["api"].stacks] == ["Orders", "Platform"]
        assert rows["api"].stack_names == "Orders|Platform"
        assert rows["lonely"].stacks == ()

    def test_a_never_checked_project_needs_attention_and_sorts_by_no_score(self):
        row = ProjectRow.for_projects([self.lonely])[0]

        assert row.head is None and row.score_value is None
        assert row.health_value == "needs-attention"
        assert row.sort_checked == ""


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ProjectListPageTests(Fixture):
    def test_the_filters_offer_health_stacks_owners_lifecycles_platforms_and_languages(self):
        search = ProjectListFilterSearch.for_rows(ProjectRow.for_projects(self.tenant.projects.all()))

        assert [f.key for f in search.fields] == [
            "health", "stack", "owner", "lifecycle", "platform", "language", "name", "path",
        ]
        owners = next(f for f in search.fields if f.key == "owner")
        assert [(v.value, v.label) for v in owners.values] == [
            ("payments team", "Payments team"), ("platform team", "Platform team"),
        ]

    def test_the_table_sorts_by_score_and_groups_by_owner_and_stack(self):
        table = ProjectListSmartTable.build()

        assert {"name", "score", "health", "owner", "checked"} <= {s.key for s in table.sorts}
        assert [g.key for g in table.groups] == ["owner", "stack", "health", "lifecycle", "platform"]

    def test_each_row_says_what_it_is_filtered_sorted_and_grouped_by(self):
        body = self.client.get(reverse("project_list")).content.decode()

        config = _smart_table_config(body)
        assert config["defaultSort"] == "name" and config["nounPlural"] == "projects"
        assert 'data-filter-stack="orders|platform"' in body
        assert 'data-group-stack="Orders|Platform"' in body
        assert 'data-group-owner="Payments team"' in body
        assert 'data-filter-owner="payments team"' in body
        assert 'data-filter-language="python"' in body
        assert 'data-sort-stacks="2"' in body
        assert 'data-sort-score=""' in body  # never checked: sorts last
        assert body.count("data-smart-row") == 3


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class StackListPageTests(Fixture):
    def test_a_stack_row_counts_its_projects_once_and_lists_their_owners(self):
        rows = {r.stack.name: r for r in StackRow.for_stacks(
            self.tenant.stacks.prefetch_related("components__project")
        )}

        assert [p.name for p in rows["Platform"].projects] == ["api", "infra"]
        assert rows["Platform"].owners == ("Payments team", "Platform team")
        assert rows["Platform"].health.needs_attention == 2
        assert rows["Platform"].health_values == "needs-attention"
        assert rows["Platform"].healthy_share == "0"

    def test_the_filters_and_the_table(self):
        rows = StackRow.for_stacks(self.tenant.stacks.prefetch_related("components__project"))
        search = StackListFilterSearch.for_rows(rows)
        table = StackListSmartTable.build()

        assert [f.key for f in search.fields] == ["has", "owner", "project", "name", "description"]
        assert [g.key for g in table.groups] == ["owner"]
        assert {"failed", "healthy", "projects", "components"} <= {s.key for s in table.sorts}

    def test_each_row_says_what_it_is_filtered_sorted_and_grouped_by(self):
        body = self.client.get(reverse("stack_list")).content.decode()

        assert 'data-group-owner="Payments team|Platform team"' in body
        assert 'data-filter-project="api|infra"' in body
        assert 'data-sort-projects="2"' in body
        assert body.count("data-smart-row") == 2


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class StandardListPageTests(Fixture):
    def setUp(self):
        super().setUp()
        from app.domain.models import StandardExecution

        status = StandardExecution.Status
        security = baker.make("app.StandardLabel", tenant=self.tenant, name="Security")
        self.secrets = baker.make(
            "app.Standard", tenant=self.tenant, name="No Secrets", enabled=True, draft=False,
            criteria={"events": ["push", "manual"]},
        )
        self.secrets.labels.add(security)
        self.api.standards.add(self.secrets)
        self.infra.standards.add(self.secrets)
        self.lonely.standards.add(self.secrets)
        for project, result in ((self.api, status.FAILED), (self.infra, status.PASSED)):
            baker.make(
                "app.StandardExecution", project=project, standard=self.secrets, standard_name="No Secrets",
                status=result, ref=project.default_branch,
            )
        # A failure on a feature branch is not the project's result.
        baker.make(
            "app.StandardExecution", project=self.infra, standard=self.secrets, standard_name="No Secrets",
            status=status.FAILED, ref="feature/x",
        )

    def test_a_standard_row_counts_its_newest_results_on_default_branches(self):
        row = StandardRow.for_standards([self.secrets])[0]

        assert (row.projects, row.passing, row.failing, row.unchecked) == (3, 1, 1, 1)
        assert row.pass_rate == "50"
        assert row.tone == "failed"
        assert row.status_value == "enabled"
        assert row.source_value == "custom"
        assert row.event_values == "push|manual"

    def test_the_table_groups_by_label_status_event_and_source(self):
        table = StandardListSmartTable.build()

        assert [g.key for g in table.groups] == ["label", "status", "event", "source"]
        assert {"failing", "rate", "projects"} <= {s.key for s in table.sorts}

    def test_each_row_says_what_it_is_sorted_and_grouped_by(self):
        body = self.client.get(reverse("standard_list")).content.decode()

        assert 'data-group-label="Security"' in body
        assert 'data-filter-event="push|manual"' in body
        assert 'data-sort-failing="1"' in body and 'data-sort-rate="50"' in body
        assert "<b>1</b> failing" in body and "<b>1</b> passing" in body
