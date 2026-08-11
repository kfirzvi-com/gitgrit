"""Workspace settings is organised into navigable, collapsible sections.

Three areas — members, git platform connections, LLM providers — each a
collapsible section reachable from a side nav. Modals stay outside the
collapsibles: a collapsed section hides its whole subtree, which would take a
<dialog> down with it.
"""
import re

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

SECTIONS = ["section-members", "section-connections", "section-llm"]
SECTION_INPUT = '<input type="radio" name="settings-section"'


def _login(client, role="owner"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestSettingsSections(TestCase):
    def test_all_three_sections_render(self):
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        for section in SECTIONS:
            assert f'id="{section}"' in body, section

    def test_side_nav_links_to_every_section(self):
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert 'id="settings-nav"' in body
        for section in SECTIONS:
            assert f'href="#{section}"' in body, section

    def test_sections_are_collapsible(self):
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert body.count("collapse-title") >= len(SECTIONS)
        assert body.count("collapse-content") >= len(SECTIONS)

    def test_sections_behave_as_an_accordion(self):
        """Radios sharing one name means opening a section closes the others."""
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert body.count(SECTION_INPUT) == len(SECTIONS)
        assert 'type="checkbox" name="settings-section"' not in body

    def test_exactly_one_section_starts_open(self):
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        section_inputs = [
            line for line in body.splitlines() if SECTION_INPUT in line
        ]
        assert len(section_inputs) == len(SECTIONS)
        assert sum("checked" in line for line in section_inputs) == 1

    def test_nav_script_targets_the_real_section_toggle(self):
        """The script must select the input the markup actually renders.

        These drifted apart once already: the toggles became radios for the
        accordion while the script still queried input[type="checkbox"], so the
        side nav silently stopped opening anything.
        """
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert 'querySelector(\'input[name="settings-section"]\')' in body
        assert 'input[type="checkbox"]' not in body

    def test_no_template_comment_leaks_into_the_page(self):
        """Django's {# #} is single-line; a wrapped one renders as body text.

        Checked for both roles, because is_admin guards whole branches of
        markup and testing one leaves the other's comments unwatched.
        """
        for role in ("owner", "member"):
            with self.subTest(role=role):
                client = self.client_class()
                _login(client, role=role)
                body = client.get(reverse("tenant_settings")).content.decode()
                assert "{#" not in body
                assert "{%" not in body

    def test_github_is_preselected_on_the_add_connection_form(self):
        """GitHub is the common case — don't make people pick it every time.

        An empty placeholder option would also leave the platform-dependent
        fields (token help, display-name suggestion) unseeded on first paint.
        """
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        select = re.search(r'<select name="platform".*?</select>', body, re.DOTALL)
        assert select, "platform select not found"
        markup = select.group(0)
        assert '<option value="github" selected>' in markup
        assert 'value=""' not in markup, "empty placeholder still competes"

    def test_init_seeds_the_platform_dependent_fields(self):
        """A server-side default only helps if the script seeds off it too."""
        _login(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert "updateDisplayNameSuggestion(platformSelect.value);" in body

    def test_dialogs_render_outside_the_collapsible_sections(self):
        _, tenant = _login(self.client)
        baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            access_token="ghp_pat",
            display_name="PAT conn",
        )
        body = self.client.get(reverse("tenant_settings")).content.decode()
        last_section_close = body.rindex("</section>")
        for dialog_id in (
            "edit-token-modal",
            "remove-connection-modal",
            "token-help-modal",
            "edit-provider-modal",
        ):
            marker = f'<dialog id="{dialog_id}"'
            assert marker in body, dialog_id
            assert body.index(marker) > last_section_close, dialog_id

    def test_member_sees_sections_without_admin_forms(self):
        _login(self.client, role="member")
        body = self.client.get(reverse("tenant_settings")).content.decode()
        for section in SECTIONS:
            assert f'id="{section}"' in body, section
        assert 'id="add-connection-card"' not in body
