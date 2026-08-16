"""Configuration that half-enables a feature must say so.

Availability is derived from the config, which means a typo or a forgotten
secret doesn't fail loudly — the feature just isn't there. The check turns that
silence into a warning at ``manage.py check`` time.
"""
from django.test import SimpleTestCase, override_settings

from app.checks import github_app_configuration
from gitgrit.feature_flags import GITHUB_APP_REQUIRED_SETTINGS


class TestGitHubAppConfigurationCheck(SimpleTestCase):
    @override_settings(GITHUB_APP_MISSING_SETTINGS=[])
    def test_a_complete_configuration_is_quiet(self):
        assert github_app_configuration(None) == []

    @override_settings(GITHUB_APP_MISSING_SETTINGS=list(GITHUB_APP_REQUIRED_SETTINGS))
    def test_no_configuration_at_all_is_quiet(self):
        """Not using the GitHub App is a legitimate choice, not a mistake."""
        assert github_app_configuration(None) == []

    @override_settings(
        GITHUB_APP_MISSING_SETTINGS=["GITHUB_APP_CLIENT_ID", "GITHUB_APP_CLIENT_SECRET"]
    )
    def test_a_partial_configuration_warns_and_names_the_gaps(self):
        """The case that bit us: an App set up before OAuth was required."""
        results = github_app_configuration(None)
        assert len(results) == 1
        warning = results[0]
        assert warning.id == "gitgrit.W001"
        assert "GITHUB_APP_CLIENT_ID" in warning.hint
        assert "GITHUB_APP_CLIENT_SECRET" in warning.hint

    @override_settings(GITHUB_APP_MISSING_SETTINGS=["GITHUB_APP_SLUG"])
    def test_a_single_gap_warns(self):
        assert len(github_app_configuration(None)) == 1

    def test_the_check_is_registered(self):
        """An unregistered check never runs, so assert it's wired in."""
        from django.core.checks import registry

        assert github_app_configuration in registry.registry.get_checks()
