"""Changing many projects at once from the Projects page: owner, lifecycle,
stacks (by component) and attached standards."""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.errors import NotFoundError
from app.application.project_bulk_edit import ProjectBulkEdit
from app.domain.models import ProjectStandard

class ProjectBulkEditTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.api = baker.make("app.Project", tenant=self.tenant, name="api", owner="Payments", lifecycle="development")
        self.web = baker.make("app.Project", tenant=self.tenant, name="web", owner="", lifecycle="production")
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Secrets", enabled=True, draft=False)
        self.edit = ProjectBulkEdit(self.tenant, baker.make("app.User"))
        self.ids = [self.api.pk, self.web.pk]

    def test_setting_the_owner_and_lifecycle(self):
        owner = self.edit.apply("set_owner", self.ids, " Platform ")
        lifecycle = self.edit.apply("set_lifecycle", self.ids, "production")

        self.api.refresh_from_db()
        assert (self.api.owner, self.api.lifecycle) == ("Platform", "production")
        assert owner.changed == 2
        assert (lifecycle.changed, lifecycle.unchanged) == (1, 1)

    def test_an_unknown_lifecycle_is_refused(self):
        with pytest.raises(ValueError):
            self.edit.apply("set_lifecycle", self.ids, "retired")

    def test_a_project_joins_a_stack_by_its_root_component_and_leaves_it_whole(self):
        extra = baker.make("app.Component", tenant=self.tenant, project=self.api, path="worker", name="worker")
        extra.stacks.add(self.stack)

        added = self.edit.apply("add_to_stack", self.ids, str(self.stack.pk))

        assert (added.changed, added.unchanged) == (2, 0)
        assert set(self.stack.components.values_list("path", flat=True)) == {"", "worker"}

        removed = self.edit.apply("remove_from_stack", [self.api.pk], str(self.stack.pk))
        assert removed.changed == 1
        assert not self.stack.components.filter(project=self.api).exists()

    def test_attaching_a_standard_with_an_importance_and_detaching_it(self):
        result = self.edit.apply("attach_standard", self.ids, str(self.standard.pk), importance_value="required")

        assert result.changed == 2
        assert set(ProjectStandard.objects.filter(standard=self.standard).values_list("importance", flat=True)) == {
            "required"
        }
        detached = self.edit.apply("detach_standard", [self.api.pk], str(self.standard.pk))
        assert detached.changed == 1 and not self.api.standards.exists()

    def test_another_workspaces_stack_is_not_found(self):
        with pytest.raises(NotFoundError):
            self.edit.apply("add_to_stack", self.ids, str(baker.make("app.Stack").pk))
