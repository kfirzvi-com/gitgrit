"""Drafts never run, so a draft can only be disabled — service layer.

The MCP tools go through ``StandardService``, so the invariant has to hold
here too, not just in the web forms.
"""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.standard_service import StandardService

VALID_CODE = (
    'def evaluate(project):\n'
    '    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'
)


@pytest.mark.django_db
class TestDraftImpliesDisabled(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.service = StandardService()

    def test_create_as_draft_is_disabled(self):
        result = self.service.create_standard(
            self.tenant, self.user, {"name": "Draft std", "code": VALID_CODE, "draft": True}
        )

        standard = self.tenant.standards.get(pk=result["id"])
        assert standard.draft is True
        assert standard.enabled is False

    def test_create_without_draft_is_enabled(self):
        result = self.service.create_standard(
            self.tenant, self.user, {"name": "Live std", "code": VALID_CODE}
        )

        standard = self.tenant.standards.get(pk=result["id"])
        assert standard.draft is False
        assert standard.enabled is True

    def test_update_to_draft_disables(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=False
        )

        self.service.update_standard(
            self.tenant, self.user, str(standard.pk), {"draft": True}
        )

        standard.refresh_from_db()
        assert standard.draft is True
        assert standard.enabled is False

    def test_leaving_draft_does_not_auto_enable(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=False, draft=True
        )

        self.service.update_standard(
            self.tenant, self.user, str(standard.pk), {"draft": False}
        )

        standard.refresh_from_db()
        assert standard.draft is False
        assert standard.enabled is False

    def test_publishing_with_enabled_true_activates(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=False, draft=True
        )

        self.service.update_standard(
            self.tenant,
            self.user,
            str(standard.pk),
            {"draft": False, "enabled": True},
        )

        standard.refresh_from_db()
        assert standard.draft is False
        assert standard.enabled is True

    def test_enabled_true_is_ignored_while_draft(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=False, draft=True
        )

        self.service.update_standard(
            self.tenant, self.user, str(standard.pk), {"enabled": True}
        )

        standard.refresh_from_db()
        assert standard.draft is True
        assert standard.enabled is False

    def test_any_update_heals_a_legacy_enabled_draft(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=True
        )

        self.service.update_standard(
            self.tenant, self.user, str(standard.pk), {"description": "touched"}
        )

        standard.refresh_from_db()
        assert standard.enabled is False
