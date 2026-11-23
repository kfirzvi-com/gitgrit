"""Changing many projects at once from the Projects page: owner, lifecycle,
stacks and attached standards."""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.errors import NotFoundError
from app.application.project_bulk_edit import ProjectBulkEdit
from app.domain.models import Project, ProjectStandard

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

    def test_projects_join_and_leave_a_stack(self):
        self.api.stacks.add(self.stack)

        added = self.edit.apply("add_to_stack", self.ids, str(self.stack.pk))

        assert (added.changed, added.unchanged) == (1, 1)
        assert set(self.stack.projects.all()) == set(Project.objects.filter(pk__in=self.ids))

        removed = self.edit.apply("remove_from_stack", [self.api.pk], str(self.stack.pk))
        assert removed.changed == 1
        assert not self.stack.projects.filter(pk=self.api.pk).exists()

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
