"""Changing many standards at once from the Standards page: each through the
one-standard use case, never outside the workspace."""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.standard_bulk_edit import StandardBulkEdit

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
