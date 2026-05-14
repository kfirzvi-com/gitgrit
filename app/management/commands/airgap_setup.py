"""First-run bootstrap for air-gapped deployments.

Run once after `docker compose -f docker-compose.prod.yml up -d`:

    docker compose exec app python manage.py airgap_setup

Idempotent. Re-runnable after env var changes (e.g. flipping a provider
on/off, rotating SITE_URL) to re-sync the Site row and SocialApp rows.

What it does:
  * Runs migrations.
  * Sanity-checks SITE_URL is set and not localhost.
  * Sanity-checks CUSTOMER_CA_PATH is set and the bundle is readable.
  * Syncs django.contrib.sites.Site row #1 with SITE_URL's hostname (if installed).
  * Deletes any SocialApp DB rows for providers disabled via AUTH_PROVIDER_*_ENABLED.
"""
import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

NON_PUBLIC_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}


class Command(BaseCommand):
    help = "Bootstrap an air-gapped GitGrit deployment."

    def handle(self, *args, **opts):
        self._check_site_url()
        self._check_ca_bundle()
        self._run_migrations()
        with transaction.atomic():
            self._sync_site_row()
            self._purge_disabled_socialapps()
        self.stdout.write(self.style.SUCCESS("Air-gap setup complete."))

    def _check_site_url(self) -> None:
        site_url = settings.SITE_URL or ""
        host = urlparse(site_url).hostname or ""
        if not site_url or host in NON_PUBLIC_HOSTS:
            raise CommandError(
                f"SITE_URL='{site_url}' (host='{host}') is not a public hostname. "
                "In production this must be reachable from your platform "
                "(e.g. internal GitLab) for webhook callbacks."
            )
        self.stdout.write(f"SITE_URL OK: {site_url}")

    def _check_ca_bundle(self) -> None:
        # Required, not optional: an unset CUSTOMER_CA_PATH defers a TLS
        # handshake failure to OAuth time — fail loud at setup instead.
        ca_path = os.environ.get("CUSTOMER_CA_PATH")
        if not ca_path:
            raise CommandError(
                "CUSTOMER_CA_PATH is not set. Set it in .env to the host path "
                "of your customer CA bundle (the issuing CA chain that signed "
                "your internal GitLab's cert). See docs/airgap.md."
            )
        # Inside the container, the bundle is mounted at a fixed path.
        # The env var holds the host-side path; we check the in-container one.
        in_container = "/etc/ssl/certs/customer-ca.pem"
        if not os.path.isfile(in_container):
            raise CommandError(
                f"CUSTOMER_CA_PATH is set ({ca_path}) but {in_container} is not "
                "readable inside the container. Check the compose volume mount."
            )
        size = os.path.getsize(in_container)
        if size == 0:
            raise CommandError(
                f"{in_container} is zero bytes. Check the host-side file at "
                f"{ca_path} is a non-empty PEM."
            )
        self.stdout.write(f"Customer CA bundle OK: {in_container} ({size} bytes)")

    def _run_migrations(self) -> None:
        self.stdout.write("Running migrations...")
        call_command("migrate", interactive=False, verbosity=1)

    def _sync_site_row(self) -> None:
        # django.contrib.sites is not installed in this project at time of
        # writing; only sync if it is. Allauth can work without it.
        if "django.contrib.sites" not in settings.INSTALLED_APPS:
            return
        from django.contrib.sites.models import Site

        host = urlparse(settings.SITE_URL).hostname
        site, _ = Site.objects.update_or_create(
            pk=getattr(settings, "SITE_ID", 1),
            defaults={"domain": host, "name": host},
        )
        self.stdout.write(f"Site row synced: {site.domain}")

    def _purge_disabled_socialapps(self) -> None:
        try:
            from allauth.socialaccount.models import SocialApp
        except ImportError as exc:
            raise CommandError(
                "allauth is not installed; cannot manage SocialApp rows."
            ) from exc

        provider_flags = {
            "github": settings.AUTH_PROVIDER_GITHUB_ENABLED,
            "gitlab": settings.AUTH_PROVIDER_GITLAB_ENABLED,
            "google": settings.AUTH_PROVIDER_GOOGLE_ENABLED,
        }
        for provider, enabled in provider_flags.items():
            if enabled:
                continue
            deleted, _ = SocialApp.objects.filter(provider=provider).delete()
            if deleted:
                self.stdout.write(
                    f"Deleted {deleted} SocialApp row(s) for disabled provider "
                    f"'{provider}'."
                )
