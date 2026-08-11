"""GitHubClient.search_projects branches by auth method.

GitHub App connections list only the repos the App is installed on via
GET /installation/repositories (a {"repositories": [...]} envelope); PAT
connections keep using GET /user/repos. All HTTP is mocked.
"""
from types import SimpleNamespace

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
    def __init__(self, json_data):
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def test_app_connection_lists_via_installation_repositories(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        # First page returns the repo envelope; second page returns empty.
        page = kw.get("params", {}).get("page", 1)
        repos = [_REPO] if page == 1 else []
        return _Resp({"repositories": repos})

    monkeypatch.setattr(
        "app.infrastructure.platform_client.requests.get", fake_get
    )
    client = GitHubClient(_conn(AuthMethod.GITHUB_APP))
    results = client.search_projects()

    assert any("/installation/repositories" in u for u in calls)
    assert all("/user/repos" not in u for u in calls)
    assert results[0]["full_path"] == "acme/app"


def test_pat_connection_lists_via_user_repos(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        page = kw.get("params", {}).get("page", 1)
        return _Resp([_REPO] if page == 1 else [])

    monkeypatch.setattr(
        "app.infrastructure.platform_client.requests.get", fake_get
    )
    client = GitHubClient(_conn(AuthMethod.PAT))
    results = client.search_projects()

    assert any("/user/repos" in u for u in calls)
    assert all("/installation/repositories" not in u for u in calls)
    assert results[0]["full_path"] == "acme/app"
