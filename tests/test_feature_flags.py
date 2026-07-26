"""GitHub App availability is derived from its configuration.

A separate on/off flag could disagree with the config behind it — on but
unusable, or fully configured but silently off. Derive it instead, and keep an
explicit switch that can only turn the feature *off*.
"""
import pytest

from gitgrit.feature_flags import (
    GITHUB_APP_REQUIRED_SETTINGS,
    github_app_enabled,
    missing_github_app_settings,
)

COMPLETE = {
    "GITHUB_APP_ID": "4396306",
    "GITHUB_APP_SLUG": "gitgrit-dev",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nx\n",
    "GITHUB_APP_WEBHOOK_SECRET": "whsec",
    "GITHUB_APP_CLIENT_ID": "Iv1.client",
    "GITHUB_APP_CLIENT_SECRET": "shhh",
}


def test_fully_configured_enables_the_feature():
    assert github_app_enabled(COMPLETE) is True
    assert missing_github_app_settings(COMPLETE) == []


@pytest.mark.parametrize("name", GITHUB_APP_REQUIRED_SETTINGS)
def test_any_missing_setting_disables_the_feature(name):
    values = dict(COMPLETE, **{name: ""})
    assert github_app_enabled(values) is False
    assert missing_github_app_settings(values) == [name]


@pytest.mark.parametrize("name", GITHUB_APP_REQUIRED_SETTINGS)
def test_whitespace_does_not_count_as_configured(name):
    values = dict(COMPLETE, **{name: "   "})
    assert github_app_enabled(values) is False


def test_absent_key_counts_as_missing():
    values = {k: v for k, v in COMPLETE.items() if k != "GITHUB_APP_SLUG"}
    assert missing_github_app_settings(values) == ["GITHUB_APP_SLUG"]


def test_every_required_setting_is_reported_at_once():
    assert sorted(missing_github_app_settings({})) == sorted(
        GITHUB_APP_REQUIRED_SETTINGS
    )


@pytest.mark.parametrize("override", ["0", "false", "False", "no", "off", " OFF "])
def test_explicit_override_turns_a_working_config_off(override):
    """The kill switch: disable a configured App without deleting its secrets."""
    assert github_app_enabled(COMPLETE, override) is False


@pytest.mark.parametrize("override", ["1", "true", "yes", "on", ""])
def test_override_cannot_turn_on_an_incomplete_config(override):
    """Asking for it doesn't make it work — the switch only ever disables."""
    values = dict(COMPLETE, GITHUB_APP_CLIENT_SECRET="")
    assert github_app_enabled(values, override) is False


@pytest.mark.parametrize("override", ["1", "true", "yes", "on", "", "   "])
def test_truthy_or_absent_override_leaves_derivation_alone(override):
    assert github_app_enabled(COMPLETE, override) is True
