"""GitHubClient branches by auth method for both listing and health checks.

GitHub App connections list only the repos the App is installed on via
GET /installation/repositories (a {"repositories": [...]} envelope); PAT
connections keep using GET /user/repos. The same split governs test_token,
because an installation token is refused by the user-scoped /user endpoint.
All HTTP is mocked.

``SimpleTestCase`` subclasses rather than bare pytest functions: CI runs
``manage.py test``, which collects only TestCase subclasses.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from app.domain.models import AuthMethod
from app.infrastructure.platform_client import GitHubClient

_REPO = {
    "id": 1,
    "name": "app",
    "full_name": "acme/app",
    "html_url": "https://github.com/acme/app",
    "default_branch": "main",
    "description": "",
}


def _conn(auth_method):
    return SimpleNamespace(
        base_url="https://api.github.com",
        access_token="t",
        auth_method=auth_method,
        get_access_token=lambda repositories=None: "t",
    )


class _Resp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class TestSearchProjectsByAuthMethod(SimpleTestCase):
    def test_app_connection_lists_via_installation_repositories(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            # First page returns the repo envelope; second page returns empty.
            page = kw.get("params", {}).get("page", 1)
            return _Resp({"repositories": [_REPO] if page == 1 else []})

        with mock.patch(
            "app.infrastructure.platform_client.requests.get", fake_get
        ):
            results = GitHubClient(_conn(AuthMethod.GITHUB_APP)).search_projects()

        self.assertTrue(any("/installation/repositories" in u for u in calls))
        self.assertTrue(all("/user/repos" not in u for u in calls))
        self.assertEqual(results[0]["full_path"], "acme/app")

    def test_pat_connection_lists_via_user_repos(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            page = kw.get("params", {}).get("page", 1)
            return _Resp([_REPO] if page == 1 else [])

        with mock.patch(
            "app.infrastructure.platform_client.requests.get", fake_get
        ):
            results = GitHubClient(_conn(AuthMethod.PAT)).search_projects()

        self.assertTrue(any("/user/repos" in u for u in calls))
        self.assertTrue(all("/installation/repositories" not in u for u in calls))
        self.assertEqual(results[0]["full_path"], "acme/app")


class TestTestTokenByAuthMethod(SimpleTestCase):
    """The connection health check ("Test" in workspace settings).

    An installation token cannot call /user — GitHub answers 403 "Resource not
    accessible by integration" — so probing it there would report every healthy
    App connection as an invalid token.
    """

    def test_app_connection_probes_installation_repositories(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return _Resp({"repositories": []}, status_code=200)

        with mock.patch(
            "app.infrastructure.platform_client.requests.get", fake_get
        ):
            ok = GitHubClient(_conn(AuthMethod.GITHUB_APP)).test_token()

        self.assertTrue(ok)
        self.assertTrue(any("/installation/repositories" in u for u in calls))
        self.assertTrue(all(not u.endswith("/user") for u in calls))

    def test_app_connection_is_not_reported_healthy_on_a_403(self):
        with mock.patch(
            "app.infrastructure.platform_client.requests.get",
            return_value=_Resp({}, status_code=403),
        ):
            self.assertFalse(GitHubClient(_conn(AuthMethod.GITHUB_APP)).test_token())

    def test_pat_connection_still_probes_user(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return _Resp({"login": "someone"}, status_code=200)

        with mock.patch(
            "app.infrastructure.platform_client.requests.get", fake_get
        ):
            ok = GitHubClient(_conn(AuthMethod.PAT)).test_token()

        self.assertTrue(ok)
        self.assertTrue(any(u.endswith("/user") for u in calls))
        self.assertTrue(all("/installation/repositories" not in u for u in calls))
