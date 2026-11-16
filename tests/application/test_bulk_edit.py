"""Bulk changes from the Projects and Standards pages: each goes through
the one-item use case, says how many changed, stayed or were skipped, and
never reaches outside the workspace."""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.bulk_edit import BulkEditResult, ProjectBulkEdit, StandardBulkEdit
from app.application.errors import NotFoundError
from app.domain.models import ProjectStandard


class BulkEditResultTests(TestCase):
    def test_the_summary_says_what_changed_stayed_and_was_skipped(self):
        result = BulkEditResult(done="Enabled", noun="standard", noun_plural="standards", changed=2, unchanged=1)
        result.skip("drafts can't be enabled")

        assert result.summary == "Enabled 2 standards; 1 already was. Skipped 1: drafts can't be enabled."
        assert result.level == "warning"


class StandardBulkEditTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.on = baker.make("app.Standard", tenant=self.tenant, name="On", enabled=True, draft=False)
        self.off = baker.make("app.Standard", tenant=self.tenant, name="Off", enabled=False, draft=False)
        self.draft = baker.make("app.Standard", tenant=self.tenant, name="Draft", enabled=False, draft=True)
        self.edit = StandardBulkEdit(self.tenant, self.user)

    def test_enabling_skips_drafts_and_counts_those_already_on(self):
        result = self.edit.apply("enable", [self.on.pk, self.off.pk, self.draft.pk])

        assert (result.changed, result.unchanged, result.skipped) == (1, 1, 1)
        self.off.refresh_from_db()
        self.draft.refresh_from_db()
        assert self.off.enabled and not self.draft.enabled

    def test_labelling_creates_the_label_once_and_matches_its_case(self):
        self.edit.apply("add_label", [self.on.pk], "Security")
        result = self.edit.apply("add_label", [self.on.pk, self.off.pk], "security")

        assert (result.changed, result.unchanged) == (1, 1)
        assert list(self.off.labels.values_list("name", flat=True)) == ["Security"]

        removed = self.edit.apply("remove_label", [self.on.pk, self.off.pk], "SECURITY")
        assert removed.changed == 2 and not self.on.labels.exists()

    def test_deleting_archives(self):
        self.edit.apply("delete", [self.on.pk])

        self.on.refresh_from_db()
        assert self.on.archived_at is not None

    def test_another_workspaces_standards_are_left_alone(self):
        theirs = baker.make("app.Standard", enabled=False, draft=False)

        result = self.edit.apply("enable", [theirs.pk])

        theirs.refresh_from_db()
        assert result.changed == 0 and not theirs.enabled

    def test_an_unknown_action_is_refused(self):
        with pytest.raises(ValueError):
            self.edit.apply("explode", [self.on.pk])


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
