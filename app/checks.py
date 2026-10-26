"""Deployment-time system checks.

Configuration that silently disables a feature is worse than configuration that
complains: the operator sets what they believe is needed, sees no error, and
finds out only when the button they expected isn't on the page. These checks run
on ``manage.py check`` / ``runserver`` / ``migrate``, so a half-configured
feature announces itself.
"""
from __future__ import annotations

import logging
import sys

from django.conf import settings
from django.core.checks import Warning as CheckWarning, register

from gitgrit.feature_flags import GITHUB_APP_REQUIRED_SETTINGS

logger = logging.getLogger(__name__)


@register()
def github_app_configuration(app_configs, **kwargs):
    """Warn when the GitHub App is configured, but not completely.

    Nothing missing (feature live) and nothing set at all (feature deliberately
    unused) are both fine. The middle — some settings present, others not — is
    the case worth saying out loud, because availability is derived from the
    config and the feature simply won't appear.
    """
    missing = list(getattr(settings, "GITHUB_APP_MISSING_SETTINGS", []))
    if not missing:
        return []
    if len(missing) == len(GITHUB_APP_REQUIRED_SETTINGS):
        return []
    return [
        CheckWarning(
            "The GitHub App integration is partially configured, so it is off.",
            hint=(
                "Set the missing settings to enable it: "
                + ", ".join(missing)
                + ". Availability is derived from configuration; "
                "GITHUB_APP_ENABLED only ever turns a working App off."
            ),
            id="gitgrit.W001",
        )
    ]


CONSOLE_EMAIL_MESSAGE = (
    "Emails are being written to the application log, tokens included "
    "(invite, password-reset and confirm links)."
)


def _console_email_hint() -> str:
    real = "|".join(name for name in settings.EMAIL_BACKENDS if name != "console")
    return (
        "Anyone who can read the logs can use those links. Set EMAIL_HOST (SMTP) "
        f"or GITGRIT_EMAIL_BACKEND={real} to send real mail."
    )


def _console_email_in_production() -> bool:
    return not settings.DEBUG and settings.EMAIL_BACKEND == settings.EMAIL_BACKENDS["console"]


@register()
def console_email_backend(app_configs, **kwargs):
    """Warn when production would print emails, and the secrets in them, to stdout.

    A warning, not an error: a misconfigured install must still start.
    """
    if not _console_email_in_production():
        return []
    return [CheckWarning(CONSOLE_EMAIL_MESSAGE, hint=_console_email_hint(), id="gitgrit.W002")]


def _is_server_or_worker(argv: list[str]) -> bool:
    """True for the web server (runserver, gunicorn) and the Procrastinate
    worker. Other commands (collectstatic, check, migrate, shell, test) are
    not the place for a startup warning."""
    if not argv:
        return False
    if "gunicorn" in argv[0]:
        return True
    return argv[1:2] == ["runserver"] or argv[1:3] == ["procrastinate", "worker"]


def log_console_email_warning(argv: list[str] | None = None) -> None:
    """Say it in the log too: ``manage.py check`` shows the system check, but
    gunicorn does not run it. Called from ``AppConfig.ready``, and logs only
    in the server and the worker, so not during ``collectstatic`` in the
    Docker build, and not twice on ``manage.py check``."""
    if not _is_server_or_worker(sys.argv if argv is None else argv):
        return
    if _console_email_in_production():
        logger.warning("%s %s", CONSOLE_EMAIL_MESSAGE, _console_email_hint())
