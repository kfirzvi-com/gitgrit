"""Standard create/edit form: enabled-toggle state.

Regression tests for the edit form silently re-enabling a disabled standard:
the template rendered the Enabled checkbox with `enabled|default:True`, and
Django's `default` filter substitutes on any falsy value, so enabled=False
rendered as checked and a plain save flipped the standard back on.
"""
import re

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import Standard

# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

VALID_CODE = (
    'def evaluate(project):\n'
    '    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'
)


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _enabled_checkbox_is_checked(body):
    match = re.search(r'<input[^>]*name="enabled"[^>]*>', body)
    assert match, "enabled checkbox not rendered"
    return "checked" in match.group(0)


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestEditFormEnabledState(TestCase):
    def test_disabled_standard_renders_unchecked(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=False, draft=False
        )

        response = self.client.get(reverse("edit_standard", args=[standard.pk]))

        assert response.status_code == 200
        assert not _enabled_checkbox_is_checked(response.content.decode())

    def test_enabled_standard_renders_checked(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=True, draft=False
        )

        response = self.client.get(reverse("edit_standard", args=[standard.pk]))

        assert response.status_code == 200
        assert _enabled_checkbox_is_checked(response.content.decode())

    def test_saving_without_touching_toggle_keeps_standard_disabled(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard",
            tenant=tenant,
            enabled=False,
            draft=False,
            code=VALID_CODE,
        )

        # An unchecked checkbox is absent from the POST — the browser submits
        # exactly this when the user saves without touching the toggle.
        response = self.client.post(
            reverse("edit_standard", args=[standard.pk]),
            {
                "name": standard.name,
                "description": standard.description,
                "code": standard.code,
                "test_cases": "[]",
            },
        )

        assert response.status_code == 302
        standard.refresh_from_db()
        assert standard.enabled is False

    def test_editor_can_still_enable_explicitly(self):
        # Relies on the standard having no attached projects: enabling a
        # non-draft standard publishes StandardSaved, which re-runs it on
        # every attached project via the sandbox engine.
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard",
            tenant=tenant,
            enabled=False,
            draft=False,
            code=VALID_CODE,
        )

        response = self.client.post(
            reverse("edit_standard", args=[standard.pk]),
            {
                "name": standard.name,
                "description": standard.description,
                "code": standard.code,
                "test_cases": "[]",
                "enabled": "true",
            },
        )

        assert response.status_code == 302
        standard.refresh_from_db()
        assert standard.enabled is True


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestCreateFormEnabledDefault(TestCase):
    def test_create_form_defaults_to_checked(self):
        _login_member(self.client)

        response = self.client.get(reverse("create_standard"))

        assert response.status_code == 200
        assert _enabled_checkbox_is_checked(response.content.decode())


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestDraftImpliesDisabled(TestCase):
    """Drafts never run, so a draft can only be disabled — at every entry point."""

    def test_create_as_draft_forces_disabled(self):
        _, tenant = _login_member(self.client)

        response = self.client.post(
            reverse("create_standard"),
            {
                "name": "My draft",
                "description": "",
                "code": VALID_CODE,
                "test_cases": "[]",
                "enabled": "true",
                "draft": "true",
            },
        )

        assert response.status_code == 302
        standard = Standard.objects.get(tenant=tenant, name="My draft")
        assert standard.draft is True
        assert standard.enabled is False

    def test_editing_to_draft_forces_disabled(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard",
            tenant=tenant,
            enabled=True,
            draft=False,
            code=VALID_CODE,
        )

        response = self.client.post(
            reverse("edit_standard", args=[standard.pk]),
            {
                "name": standard.name,
                "description": standard.description,
                "code": standard.code,
                "test_cases": "[]",
                "enabled": "true",
                "draft": "true",
            },
        )

        assert response.status_code == 302
        standard.refresh_from_db()
        assert standard.draft is True
        assert standard.enabled is False

    def test_toggle_refuses_to_enable_a_draft(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=False, draft=True
        )

        response = self.client.post(
            reverse("toggle_standard", args=[standard.pk]),
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        assert "Disabled" in response.content.decode()
        standard.refresh_from_db()
        assert standard.enabled is False

    def test_toggle_refusal_without_htmx_flashes_and_redirects(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=False, draft=True
        )

        response = self.client.post(
            reverse("toggle_standard", args=[standard.pk]), follow=True
        )

        assert response.redirect_chain[-1][0] == reverse("standard_list")
        messages = [str(m) for m in response.context["messages"]]
        assert any("Draft standards can't be enabled" in m for m in messages)
        standard.refresh_from_db()
        assert standard.enabled is False

    def test_toggle_still_disables_an_enabled_standard(self):
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=True, draft=False
        )

        response = self.client.post(
            reverse("toggle_standard", args=[standard.pk]),
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        standard.refresh_from_db()
        assert standard.enabled is False

    def test_toggle_disables_a_legacy_enabled_draft(self):
        # Rows predating the invariant could be enabled+draft; one click
        # disables them, after which the refusal guard applies.
        _, tenant = _login_member(self.client)
        standard = baker.make(
            "app.Standard", tenant=tenant, enabled=True, draft=True
        )

        response = self.client.post(
            reverse("toggle_standard", args=[standard.pk]),
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        standard.refresh_from_db()
        assert standard.enabled is False

    def test_form_shows_draft_clarification_note(self):
        _login_member(self.client)

        response = self.client.get(reverse("create_standard"))

        assert "Draft standards are always disabled" in response.content.decode()
