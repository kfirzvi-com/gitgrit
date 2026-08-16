"""Feature availability derived from configuration.

Deliberately free of Django imports so ``settings`` can use it while it is
still being built.
"""
from __future__ import annotations

# Everything the GitHub App needs before it can complete an install end to end:
# identify itself (id/slug), authenticate as the App (private key), verify its
# webhook deliveries (webhook secret), and prove a user may access the
# installation they came back with (the OAuth pair). Missing any one of these
# leaves the flow broken partway, so treat them as a single unit.
GITHUB_APP_REQUIRED_SETTINGS = (
    "GITHUB_APP_ID",
    "GITHUB_APP_SLUG",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_WEBHOOK_SECRET",
    "GITHUB_APP_CLIENT_ID",
    "GITHUB_APP_CLIENT_SECRET",
)

_DISABLING_VALUES = {"0", "false", "no", "off"}


def missing_github_app_settings(values: dict) -> list[str]:
    """Which required settings are absent or blank, in declaration order."""
    return [
        name
        for name in GITHUB_APP_REQUIRED_SETTINGS
        if not str(values.get(name) or "").strip()
    ]


def github_app_enabled(values: dict, override: str = "") -> bool:
    """Whether the GitHub App feature should be live.

    Derived from the configuration rather than announced separately, so the
    flag cannot claim the feature works when it can't. ``override`` is a kill
    switch — it can turn a working configuration off (useful for disabling the
    feature in an incident without destroying its secrets) but never turns an
    incomplete one on.
    """
    if str(override or "").strip().lower() in _DISABLING_VALUES:
        return False
    return not missing_github_app_settings(values)
