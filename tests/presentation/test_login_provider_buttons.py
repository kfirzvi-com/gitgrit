"""The login page must show exactly the auth-provider buttons that match
the operator's `AUTH_PROVIDER_*_ENABLED` flags. This is the "connect"
half of air-gap install/connect: an operator who flipped GitHub off in
`.env` should not see a GitHub button that would 500 on click because
there's no SocialApp row + no internet to reach github.com.
"""
from django.test import TestCase, override_settings

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


@override_settings(STORAGES=_PLAIN_STATICFILES)
class TestLoginProviderButtons(TestCase):
    def test_buttons_match_provider_flags(self):
        cases = [
            # Air-gap default per .env.example: GitLab only.
            (False, True, False, {"GitLab"}),
            # Cloud / hosted default: all three on.
            (True, True, True, {"GitHub", "GitLab", "Google"}),
            # Misconfigured air-gap install with everything off — page must
            # still render so the operator can see they have nothing wired up.
            (False, False, False, set()),
        ]
        for github, gitlab, google, expected in cases:
            with self.subTest(github=github, gitlab=gitlab, google=google):
                with self.settings(
                    AUTH_PROVIDER_GITHUB_ENABLED=github,
                    AUTH_PROVIDER_GITLAB_ENABLED=gitlab,
                    AUTH_PROVIDER_GOOGLE_ENABLED=google,
                ):
                    response = self.client.get(LOGIN_URL)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    _provider_buttons(response.content.decode()), expected
                )
