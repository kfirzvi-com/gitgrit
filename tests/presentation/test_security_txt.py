"""How to report a vulnerability (SOC 2 CC2.3): /.well-known/security.txt
(RFC 9116) and /security/, the stable address the footer links to.
Both are public and work before first-run setup."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings, tag
from model_bakery import baker

ROOT = Path(__file__).resolve().parents[2]
POLICY = "https://github.com/kfirzvi-com/gitgrit/blob/main/SECURITY.md"
ADVISORY = "https://github.com/kfirzvi-com/gitgrit/security/advisories/new"
DEFAULT_EMAIL = "kfir@kfirzvi.com"

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _fields(body):
    fields = {}
    for line in body.splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition(": ")
            fields.setdefault(name, []).append(value)
    return fields


def _expires(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@tag("security")
@override_settings(SITE_URL="https://app.gitgrit.dev")
class SecurityTxtTests(TestCase):
    def setUp(self):
        self.response = self.client.get("/.well-known/security.txt")
        self.fields = _fields(self.response.content.decode())

    def test_served_as_plain_text_without_login(self):
        assert self.response.status_code == 200
        assert self.response["Content-Type"].startswith("text/plain")

    def test_head_request_is_ok(self):
        assert self.client.head("/.well-known/security.txt").status_code == 200
        assert self.client.head("/security/").status_code == 302

    def test_lists_the_same_contacts_as_security_md(self):
        assert self.fields["Contact"] == [f"mailto:{settings.SECURITY_CONTACT_EMAIL}", ADVISORY]

    def test_expires_is_the_fixed_review_date_within_a_year(self):
        # RFC 9116: required, and less than a year ahead is recommended.
        assert self.fields["Expires"] == [settings.SECURITY_TXT_EXPIRES]
        assert _expires(settings.SECURITY_TXT_EXPIRES) <= datetime.now(timezone.utc) + timedelta(
            days=366
        )

    def test_expires_is_not_close_to_lapsing(self):
        left = _expires(settings.SECURITY_TXT_EXPIRES) - datetime.now(timezone.utc)
        assert left > timedelta(days=30), (
            "SECURITY_TXT_EXPIRES is less than 30 days away: review security.txt "
            "contacts and move SECURITY_TXT_EXPIRES forward"
        )

    def test_points_at_the_policy_and_itself(self):
        assert self.fields["Policy"] == ["https://app.gitgrit.dev/security/"]
        assert self.fields["Canonical"] == ["https://app.gitgrit.dev/.well-known/security.txt"]
        assert self.fields["Preferred-Languages"] == ["en"]

    @override_settings(SITE_URL="http://localhost:8000")
    def test_canonical_is_left_out_without_https(self):
        fields = _fields(self.client.get("/.well-known/security.txt").content.decode())
        assert "Canonical" not in fields
        assert fields["Policy"] == ["http://localhost:8000/security/"]

    @override_settings(SECURITY_CONTACT_EMAIL="security@acme.example")
    def test_contact_email_is_a_setting(self):
        body = self.client.get("/.well-known/security.txt").content.decode()
        assert "Contact: mailto:security@acme.example" in body

    @override_settings(SECURITY_ADVISORY_URL="https://sec.acme.example/report")
    def test_advisory_url_is_a_setting(self):
        fields = _fields(self.client.get("/.well-known/security.txt").content.decode())
        assert fields["Contact"][1] == "https://sec.acme.example/report"

    @override_settings(AIRGAPPED=True, SECURITY_ADVISORY_URL_IS_CUSTOM=False)
    def test_airgapped_leaves_out_the_github_advisory(self):
        fields = _fields(self.client.get("/.well-known/security.txt").content.decode())
        assert fields["Contact"] == [f"mailto:{settings.SECURITY_CONTACT_EMAIL}"]

    @override_settings(
        AIRGAPPED=True,
        SECURITY_ADVISORY_URL="https://sec.acme.internal/report",
        SECURITY_ADVISORY_URL_IS_CUSTOM=True,
    )
    def test_airgapped_keeps_an_explicit_advisory_url(self):
        fields = _fields(self.client.get("/.well-known/security.txt").content.decode())
        assert "https://sec.acme.internal/report" in fields["Contact"]


@tag("security")
class DisclosureRouteTests(TestCase):
    def test_security_page_leads_to_the_policy(self):
        response = self.client.get("/security/")
        assert response.status_code == 302
        assert response["Location"] == POLICY

    @override_settings(SECURITY_POLICY_URL="https://sec.acme.example/policy")
    def test_policy_url_is_a_setting(self):
        assert self.client.get("/security/")["Location"] == "https://sec.acme.example/policy"

    @override_settings(STORAGES=NON_MANIFEST_STORAGES)
    def test_footer_links_to_the_stable_address(self):
        user = baker.make("app.User")
        self.client.force_login(user)
        response = self.client.get("/profile/")
        assert response.status_code == 200
        body = response.content.decode()
        assert re.search(r'<a [^>]*href="/security/"[^>]*>Security</a>', body)
        assert not re.search(r'<a [^>]*href="/security/"[^>]*target=', body)

    def test_signed_in_user_with_no_workspace_can_read_both(self):
        # The footer links here from the no-workspace page; it must not loop back.
        self.client.force_login(baker.make("app.User"))
        assert self.client.get("/.well-known/security.txt").status_code == 200
        response = self.client.get("/security/")
        assert response.status_code == 302
        assert response["Location"] == POLICY


@tag("security")
class SettingsDefaultTests(TestCase):
    """docker-compose passes empty values for unset variables; they must mean
    the default, so settings.py is the only place a default lives."""

    def _reload(self, **env):
        import importlib
        import os
        from unittest import mock

        import gitgrit.settings as module

        with mock.patch.dict(os.environ, env):
            return importlib.reload(module)

    def tearDown(self):
        self._reload()

    def test_empty_values_fall_back_to_the_defaults(self):
        module = self._reload(
            SECURITY_CONTACT_EMAIL="", SECURITY_ADVISORY_URL="", SECURITY_POLICY_URL=""
        )
        assert module.SECURITY_CONTACT_EMAIL == DEFAULT_EMAIL
        assert module.SECURITY_ADVISORY_URL == ADVISORY
        assert module.SECURITY_POLICY_URL == POLICY
        assert module.SECURITY_ADVISORY_URL_IS_CUSTOM is False

    def test_set_values_win(self):
        module = self._reload(SECURITY_ADVISORY_URL="https://x.example/r")
        assert module.SECURITY_ADVISORY_URL == "https://x.example/r"
        assert module.SECURITY_ADVISORY_URL_IS_CUSTOM is True

    def test_defaults_are_built_from_the_repo_url(self):
        assert settings.GITHUB_REPO_URL == "https://github.com/kfirzvi-com/gitgrit"
        assert POLICY.startswith(settings.GITHUB_REPO_URL)
        assert ADVISORY.startswith(settings.GITHUB_REPO_URL)


@tag("security")
class PublishedContactsTests(TestCase):
    """SECURITY.md and the docs site's static security.txt must not drift from the app."""

    def test_security_md_has_the_default_contacts(self):
        text = (ROOT / "SECURITY.md").read_text()
        assert ADVISORY in text
        assert DEFAULT_EMAIL in text

    def test_docs_site_file_matches_the_app(self):
        path = ROOT / "site/docs/.well-known/security.txt"
        fields = _fields(path.read_text())
        assert fields["Contact"] == [f"mailto:{DEFAULT_EMAIL}", ADVISORY]
        assert fields["Expires"] == [settings.SECURITY_TXT_EXPIRES]
        assert fields["Policy"] == [POLICY]
        assert fields["Canonical"] == ["https://gitgrit.dev/.well-known/security.txt"]
        assert fields["Preferred-Languages"] == ["en"]


@tag("security")
@override_settings(FIRST_RUN_SETUP_ENABLED=True)
class BeforeFirstRunSetupTests(TestCase):
    """A fresh install with no users sends pages to /setup/; how to report a
    vulnerability must still be reachable, but nothing else under it."""

    def test_security_txt_and_policy_are_not_redirected_to_setup(self):
        assert self.client.get("/.well-known/security.txt").status_code == 200
        assert self.client.get("/security/")["Location"] == POLICY

    def test_other_well_known_paths_still_wait_for_setup(self):
        response = self.client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 302
        assert response["Location"] == "/setup/"
