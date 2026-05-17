"""The login page must show exactly the auth-provider buttons that match
the operator's `AUTH_PROVIDER_*_ENABLED` flags. This is the "connect"
half of air-gap install/connect: an operator who flipped GitHub off in
`.env` should not see a GitHub button that would 500 on click because
there's no SocialApp row + no internet to reach github.com.
"""
import pytest


LOGIN_URL = "/accounts/login/"

# Production uses ManifestStaticFilesStorage, which requires `collectstatic`
# to have populated the manifest. Tests don't run that step, so we swap to
# the plain backend here so base.html's `{% static %}` calls don't 500 on
# every render.
_PLAIN_STATICFILES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


def _provider_buttons(html: str) -> set[str]:
    """Return the set of provider names whose 'Continue with <Provider>'
    button is rendered on the page."""
    return {
        name
        for name in ("GitHub", "GitLab", "Google")
        if f"Continue with {name}" in html
    }


@pytest.mark.django_db
class TestLoginProviderButtons:
    @pytest.fixture(autouse=True)
    def _plain_staticfiles(self, settings):
        settings.STORAGES = _PLAIN_STATICFILES

    @pytest.mark.parametrize(
        "github,gitlab,google,expected",
        [
            # Air-gap default per .env.example: GitLab only.
            (False, True, False, {"GitLab"}),
            # Cloud / hosted default: all three on.
            (True, True, True, {"GitHub", "GitLab", "Google"}),
            # Misconfigured air-gap install with everything off — page must
            # still render so the operator can see they have nothing wired up.
            (False, False, False, set()),
        ],
    )
    def test_buttons_match_provider_flags(
        self, client, settings, github, gitlab, google, expected
    ):
        settings.AUTH_PROVIDER_GITHUB_ENABLED = github
        settings.AUTH_PROVIDER_GITLAB_ENABLED = gitlab
        settings.AUTH_PROVIDER_GOOGLE_ENABLED = google

        response = client.get(LOGIN_URL)

        assert response.status_code == 200
        assert _provider_buttons(response.content.decode()) == expected
