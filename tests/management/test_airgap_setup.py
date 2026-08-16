"""Tests for the `airgap_setup` first-run install command.

This is the command an operator runs once after `docker compose up`. It is
the install/connect entry point for an air-gapped deployment, so every
failure-mode branch here matters: a silent miss means the customer brings
up a broken stack and finds out at first login.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from tests.support import MonkeyPatchMixin


def _run():
    """Invoke `airgap_setup` with stdout captured. Returns the captured text."""
    out = StringIO()
    call_command("airgap_setup", stdout=out)
    return out.getvalue()


class _AirgapTestCase(MonkeyPatchMixin, TestCase):
    def override(self, **kwargs):
        """Mutable-settings equivalent of pytest-django's `settings` fixture."""
        ctx = override_settings(**kwargs)
        ctx.enable()
        self.addCleanup(ctx.disable)


class TestCheckSiteUrl(_AirgapTestCase):
    """`SITE_URL` must be a real public hostname — air-gap webhook callbacks
    from the customer's GitLab can't reach `localhost`."""

    def test_rejects_non_public_host(self):
        bad_urls = [
            "",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://0.0.0.0/",
            "http://[::1]/",
        ]
        for bad_url in bad_urls:
            with self.subTest(url=bad_url):
                with override_settings(SITE_URL=bad_url):
                    with self.assertRaisesRegex(
                        CommandError, "not a public hostname"
                    ):
                        call_command("airgap_setup")

    def test_accepts_public_host(self):
        # A reachable hostname should pass the SITE_URL check. We patch the
        # downstream side effects so the test stays focused on this branch.
        self.override(SITE_URL="https://gitgrit.acme.internal")
        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            out = _run()
        self.assertIn("SITE_URL OK: https://gitgrit.acme.internal", out)


class TestCheckCaBundle(_AirgapTestCase):
    """The operator CA bundle is the linchpin of air-gap TLS — a missing or
    empty file means every outbound request to the operator's GitLab fails
    with a verify error. We hard-fail at install time so the operator can't
    miss it."""

    IN_CONTAINER = "/etc/ssl/certs/custom-ca.pem"

    def test_errors_when_env_var_unset(self):
        # GITGRIT_CUSTOM_CA_FILE_PATH is required, not optional: TLS to the
        # internal GitLab needs it. Setup must fail loud here so the operator
        # finds out at install time, not at first OAuth handshake.
        self.override(SITE_URL="https://gitgrit.acme.internal")
        self.monkeypatch.delenv("GITGRIT_CUSTOM_CA_FILE_PATH", raising=False)
        with self.assertRaisesRegex(
            CommandError, "GITGRIT_CUSTOM_CA_FILE_PATH is not set"
        ):
            call_command("airgap_setup")

    def test_errors_when_mount_missing(self):
        self.override(SITE_URL="https://gitgrit.acme.internal")
        self.monkeypatch.setenv(
            "GITGRIT_CUSTOM_CA_FILE_PATH", "/opt/gitgrit/ca-bundle.pem"
        )
        with mock.patch(
            "app.management.commands.airgap_setup.os.path.isfile",
            return_value=False,
        ):
            with self.assertRaisesRegex(CommandError, "readable inside the container"):
                call_command("airgap_setup")

    def test_errors_when_bundle_zero_bytes(self):
        self.override(SITE_URL="https://gitgrit.acme.internal")
        self.monkeypatch.setenv(
            "GITGRIT_CUSTOM_CA_FILE_PATH", "/opt/gitgrit/ca-bundle.pem"
        )
        with mock.patch(
            "app.management.commands.airgap_setup.os.path.isfile",
            return_value=True,
        ), mock.patch(
            "app.management.commands.airgap_setup.os.path.getsize",
            return_value=0,
        ):
            with self.assertRaisesRegex(CommandError, "zero bytes"):
                call_command("airgap_setup")

    def test_accepts_valid_bundle(self):
        self.override(SITE_URL="https://gitgrit.acme.internal")
        self.monkeypatch.setenv(
            "GITGRIT_CUSTOM_CA_FILE_PATH", "/opt/gitgrit/ca-bundle.pem"
        )
        with mock.patch(
            "app.management.commands.airgap_setup.os.path.isfile",
            return_value=True,
        ), mock.patch(
            "app.management.commands.airgap_setup.os.path.getsize",
            return_value=4096,
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ):
            out = _run()
        self.assertIn(
            f"Operator CA bundle OK: {self.IN_CONTAINER} (4096 bytes)", out
        )


class TestPurgeDisabledSocialapps(_AirgapTestCase):
    """If the operator disables a provider in `.env` (e.g. flips
    AUTH_PROVIDER_GITHUB_ENABLED=False) and re-runs `airgap_setup`, any
    leftover SocialApp row for that provider must be purged. Otherwise
    allauth still tries to render the login button for it and 500s when
    the SocialApp lookup succeeds but the URL conf has no route."""

    def setUp(self):
        super().setUp()
        from allauth.socialaccount.models import SocialApp

        SocialApp.objects.filter(
            provider__in=("github", "gitlab", "google")
        ).delete()

    def _seed(self, provider: str):
        from allauth.socialaccount.models import SocialApp

        return SocialApp.objects.create(
            provider=provider,
            name=f"{provider}-test",
            client_id="cid",
            secret="secret",
        )

    def _run_patched(self):
        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            return _run()

    def test_deletes_row_for_disabled_provider(self):
        from allauth.socialaccount.models import SocialApp

        self.override(
            SITE_URL="https://gitgrit.acme.internal",
            AUTH_PROVIDER_GITHUB_ENABLED=False,
            AUTH_PROVIDER_GITLAB_ENABLED=True,
            AUTH_PROVIDER_GOOGLE_ENABLED=False,
        )
        self._seed("github")
        self._seed("gitlab")
        self._seed("google")

        out = self._run_patched()

        self.assertFalse(SocialApp.objects.filter(provider="github").exists())
        self.assertFalse(SocialApp.objects.filter(provider="google").exists())
        self.assertTrue(SocialApp.objects.filter(provider="gitlab").exists())
        self.assertIn(
            "Deleted 1 SocialApp row(s) for disabled provider 'github'.", out
        )
        self.assertIn(
            "Deleted 1 SocialApp row(s) for disabled provider 'google'.", out
        )

    def test_keeps_all_when_all_enabled(self):
        from allauth.socialaccount.models import SocialApp

        self.override(
            SITE_URL="https://gitgrit.acme.internal",
            AUTH_PROVIDER_GITHUB_ENABLED=True,
            AUTH_PROVIDER_GITLAB_ENABLED=True,
            AUTH_PROVIDER_GOOGLE_ENABLED=True,
        )
        self._seed("github")
        self._seed("gitlab")
        self._seed("google")

        self._run_patched()

        self.assertTrue(SocialApp.objects.filter(provider="github").exists())
        self.assertTrue(SocialApp.objects.filter(provider="gitlab").exists())
        self.assertTrue(SocialApp.objects.filter(provider="google").exists())

    def test_idempotent_when_no_rows_to_delete(self):
        # The customer may re-run airgap_setup after every .env change. If
        # there's nothing to purge, the command must succeed silently and
        # not log a misleading "Deleted 0" line.
        self.override(
            SITE_URL="https://gitgrit.acme.internal",
            AUTH_PROVIDER_GITHUB_ENABLED=False,
            AUTH_PROVIDER_GITLAB_ENABLED=True,
            AUTH_PROVIDER_GOOGLE_ENABLED=False,
        )

        out = self._run_patched()

        self.assertNotIn("Deleted", out)
        self.assertIn("Air-gap setup complete.", out)
