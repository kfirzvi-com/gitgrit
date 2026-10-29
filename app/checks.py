"""Deployment-time system checks.

Configuration that silently disables a feature is worse than configuration that
complains: the operator sets what they believe is needed, sees no error, and
finds out only when the button they expected isn't on the page. These checks run
on ``manage.py check`` / ``runserver`` / ``migrate``, so a half-configured
feature announces itself.
"""
from __future__ import annotations

from django.conf import settings
from django.core.checks import Warning as CheckWarning, register

from gitgrit.feature_flags import GITHUB_APP_REQUIRED_SETTINGS


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
