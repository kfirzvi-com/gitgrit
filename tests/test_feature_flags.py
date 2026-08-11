"""GitHub App availability is derived from its configuration.

A separate on/off flag could disagree with the config behind it — on but
unusable, or fully configured but silently off. Derive it instead, and keep an
explicit switch that can only turn the feature *off*.

Written as a ``SimpleTestCase`` (no database needed) rather than bare pytest
functions: CI runs ``manage.py test``, whose unittest loader collects only
``TestCase`` subclasses, so module-level ``test_*`` functions would never run
there. ``subTest`` stands in for ``parametrize`` and still reports each case
separately.
"""
from django.test import SimpleTestCase

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

DISABLING_OVERRIDES = ["0", "false", "False", "no", "off", " OFF "]
NON_DISABLING_OVERRIDES = ["1", "true", "yes", "on", "", "   "]


class TestGitHubAppAvailability(SimpleTestCase):
    def test_fully_configured_enables_the_feature(self):
        self.assertIs(github_app_enabled(COMPLETE), True)
        self.assertEqual(missing_github_app_settings(COMPLETE), [])

    def test_any_missing_setting_disables_the_feature(self):
        for name in GITHUB_APP_REQUIRED_SETTINGS:
            with self.subTest(setting=name):
                values = dict(COMPLETE, **{name: ""})
                self.assertIs(github_app_enabled(values), False)
                self.assertEqual(missing_github_app_settings(values), [name])

    def test_whitespace_does_not_count_as_configured(self):
        for name in GITHUB_APP_REQUIRED_SETTINGS:
            with self.subTest(setting=name):
                values = dict(COMPLETE, **{name: "   "})
                self.assertIs(github_app_enabled(values), False)

    def test_absent_key_counts_as_missing(self):
        values = {k: v for k, v in COMPLETE.items() if k != "GITHUB_APP_SLUG"}
        self.assertEqual(missing_github_app_settings(values), ["GITHUB_APP_SLUG"])

    def test_every_required_setting_is_reported_at_once(self):
        self.assertEqual(
            sorted(missing_github_app_settings({})),
            sorted(GITHUB_APP_REQUIRED_SETTINGS),
        )

    def test_the_complete_set_matches_what_settings_wires_up(self):
        """The required list and the settings module must not drift apart."""
        self.assertEqual(sorted(COMPLETE), sorted(GITHUB_APP_REQUIRED_SETTINGS))

    def test_explicit_override_turns_a_working_config_off(self):
        """The kill switch: disable a configured App without deleting its secrets."""
        for override in DISABLING_OVERRIDES:
            with self.subTest(override=override):
                self.assertIs(github_app_enabled(COMPLETE, override), False)

    def test_override_cannot_turn_on_an_incomplete_config(self):
        """Asking for it doesn't make it work — the switch only ever disables."""
        values = dict(COMPLETE, GITHUB_APP_CLIENT_SECRET="")
        for override in NON_DISABLING_OVERRIDES:
            with self.subTest(override=override):
                self.assertIs(github_app_enabled(values, override), False)

    def test_truthy_or_absent_override_leaves_derivation_alone(self):
        for override in NON_DISABLING_OVERRIDES:
            with self.subTest(override=override):
                self.assertIs(github_app_enabled(COMPLETE, override), True)

    def test_none_override_is_treated_as_absent(self):
        self.assertIs(github_app_enabled(COMPLETE, None), True)
