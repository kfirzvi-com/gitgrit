"""Tests for the `airgap_setup` first-run install command.

This is the command an operator runs once after `docker compose up`. It is
the install/connect entry point for an air-gapped deployment, so every
failure-mode branch here matters: a silent miss means the customer brings
up a broken stack and finds out at first login.
"""
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def _run(**settings_overrides):
    """Invoke `airgap_setup` with stdout captured. Returns the captured text."""
    out = StringIO()
    call_command("airgap_setup", stdout=out)
    return out.getvalue()


class TestCheckSiteUrl:
    """`SITE_URL` must be a real public hostname — air-gap webhook callbacks
    from the customer's GitLab can't reach `localhost`."""

    @pytest.mark.parametrize(
        "bad_url",
        [
            "",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://0.0.0.0/",
            "http://[::1]/",
        ],
    )
    def test_rejects_non_public_host(self, settings, bad_url):
        settings.SITE_URL = bad_url
        with pytest.raises(CommandError, match="not a public hostname"):
            call_command("airgap_setup")

    def test_accepts_public_host(self, settings, db):
        # A reachable hostname should pass the SITE_URL check. We patch the
        # downstream side effects so the test stays focused on this branch.
        settings.SITE_URL = "https://gitgrit.acme.internal"
        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            out = _run()
        assert "SITE_URL OK: https://gitgrit.acme.internal" in out


class TestCheckCaBundle:
    """The customer CA bundle is the linchpin of air-gap TLS — a missing or
    empty file means every outbound request to the customer's GitLab fails
    with a verify error. We hard-fail at install time so the operator can't
    miss it."""

    IN_CONTAINER = "/etc/ssl/certs/customer-ca.pem"

    def test_skips_when_env_var_unset(self, settings, db, monkeypatch):
        settings.SITE_URL = "https://gitgrit.acme.internal"
        monkeypatch.delenv("CUSTOMER_CA_PATH", raising=False)
        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ):
            out = _run()
        assert "CUSTOMER_CA_PATH not set; skipping CA bundle check." in out

    def test_errors_when_mount_missing(self, settings, monkeypatch):
        settings.SITE_URL = "https://gitgrit.acme.internal"
        monkeypatch.setenv("CUSTOMER_CA_PATH", "/opt/gitgrit/ca-bundle.pem")
        with mock.patch(
            "app.management.commands.airgap_setup.os.path.isfile",
            return_value=False,
        ):
            with pytest.raises(CommandError, match="readable inside the container"):
                call_command("airgap_setup")

    def test_errors_when_bundle_zero_bytes(self, settings, monkeypatch):
        settings.SITE_URL = "https://gitgrit.acme.internal"
        monkeypatch.setenv("CUSTOMER_CA_PATH", "/opt/gitgrit/ca-bundle.pem")
        with mock.patch(
            "app.management.commands.airgap_setup.os.path.isfile",
            return_value=True,
        ), mock.patch(
            "app.management.commands.airgap_setup.os.path.getsize",
            return_value=0,
        ):
            with pytest.raises(CommandError, match="zero bytes"):
                call_command("airgap_setup")

    def test_accepts_valid_bundle(self, settings, db, monkeypatch):
        settings.SITE_URL = "https://gitgrit.acme.internal"
        monkeypatch.setenv("CUSTOMER_CA_PATH", "/opt/gitgrit/ca-bundle.pem")
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
        assert f"Customer CA bundle OK: {self.IN_CONTAINER} (4096 bytes)" in out


@pytest.mark.django_db
class TestPurgeDisabledSocialapps:
    """If the operator disables a provider in `.env` (e.g. flips
    AUTH_PROVIDER_GITHUB_ENABLED=False) and re-runs `airgap_setup`, any
    leftover SocialApp row for that provider must be purged. Otherwise
    allauth still tries to render the login button for it and 500s when
    the SocialApp lookup succeeds but the URL conf has no route."""

    def setup_method(self):
        from allauth.socialaccount.models import SocialApp

        SocialApp.objects.filter(provider__in=("github", "gitlab", "google")).delete()

    def _seed(self, provider: str):
        from allauth.socialaccount.models import SocialApp

        return SocialApp.objects.create(
            provider=provider,
            name=f"{provider}-test",
            client_id="cid",
            secret="secret",
        )

    def test_deletes_row_for_disabled_provider(self, settings):
        from allauth.socialaccount.models import SocialApp

        settings.SITE_URL = "https://gitgrit.acme.internal"
        settings.AUTH_PROVIDER_GITHUB_ENABLED = False
        settings.AUTH_PROVIDER_GITLAB_ENABLED = True
        settings.AUTH_PROVIDER_GOOGLE_ENABLED = False
        self._seed("github")
        self._seed("gitlab")
        self._seed("google")

        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            out = _run()

        assert not SocialApp.objects.filter(provider="github").exists()
        assert not SocialApp.objects.filter(provider="google").exists()
        assert SocialApp.objects.filter(provider="gitlab").exists()
        assert "Deleted 1 SocialApp row(s) for disabled provider 'github'." in out
        assert "Deleted 1 SocialApp row(s) for disabled provider 'google'." in out

    def test_keeps_all_when_all_enabled(self, settings):
        from allauth.socialaccount.models import SocialApp

        settings.SITE_URL = "https://gitgrit.acme.internal"
        settings.AUTH_PROVIDER_GITHUB_ENABLED = True
        settings.AUTH_PROVIDER_GITLAB_ENABLED = True
        settings.AUTH_PROVIDER_GOOGLE_ENABLED = True
        self._seed("github")
        self._seed("gitlab")
        self._seed("google")

        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            _run()

        assert SocialApp.objects.filter(provider="github").exists()
        assert SocialApp.objects.filter(provider="gitlab").exists()
        assert SocialApp.objects.filter(provider="google").exists()

    def test_idempotent_when_no_rows_to_delete(self, settings):
        # The customer may re-run airgap_setup after every .env change. If
        # there's nothing to purge, the command must succeed silently and
        # not log a misleading "Deleted 0" line.
        settings.SITE_URL = "https://gitgrit.acme.internal"
        settings.AUTH_PROVIDER_GITHUB_ENABLED = False
        settings.AUTH_PROVIDER_GITLAB_ENABLED = True
        settings.AUTH_PROVIDER_GOOGLE_ENABLED = False

        with mock.patch(
            "app.management.commands.airgap_setup.Command._run_migrations"
        ), mock.patch(
            "app.management.commands.airgap_setup.Command._check_ca_bundle"
        ):
            out = _run()

        assert "Deleted" not in out
        assert "Air-gap setup complete." in out
