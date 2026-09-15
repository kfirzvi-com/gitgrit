"""``GitHubClient.set_commit_status`` posts the ``gitgrit/grade`` status;
``get_branch_head`` finds the commit for runs that have none of their own."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.infrastructure.platform_client import GitHubClient
from tests.support import MonkeyPatchMixin


class _Resp:
    def __init__(self, status=201, json_data=None):
        self.status_code = status
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


def _client():
    return GitHubClient(
        SimpleNamespace(
            base_url="https://api.github.com",
            auth_method="pat",
            get_access_token=lambda repositories=None: "t",
        )
    )


class GitHubCommitStatusTests(MonkeyPatchMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return _Resp()

        self.monkeypatch.setattr(
            "app.infrastructure.platform_client.requests.post", fake_post
        )

    def test_posts_to_the_statuses_endpoint(self):
        _client().set_commit_status(
            "acme/repo", "abc123", "failure", "Grade warning · 62/100", "https://g/p/1/"
        )
        assert len(self.calls) == 1
        call = self.calls[0]
        assert call["url"] == "https://api.github.com/repos/acme/repo/statuses/abc123"
        assert call["headers"]["Authorization"] == "Bearer t"
        assert call["json"] == {
            "state": "failure",
            "description": "Grade warning · 62/100",
            "context": "gitgrit/grade",
            "target_url": "https://g/p/1/",
        }

    def test_description_is_capped_at_140_chars(self):
        _client().set_commit_status("acme/repo", "abc", "success", "x" * 200, "https://g/")
        assert self.calls[0]["json"]["description"] == "x" * 140

    def test_http_error_raises(self):
        self.monkeypatch.setattr(
            "app.infrastructure.platform_client.requests.post",
            lambda *a, **k: _Resp(403),
        )
        with self.assertRaises(AssertionError):
            _client().set_commit_status("acme/repo", "abc", "success", "d", "https://g/")


class GitHubBranchHeadTests(MonkeyPatchMixin, SimpleTestCase):
    def _patch_get(self, resp):
        self.calls = []

        def fake_get(url, headers=None, timeout=None, **_):
            self.calls.append(url)
            return resp

        self.monkeypatch.setattr("app.infrastructure.platform_client.requests.get", fake_get)

    def test_returns_the_tip_sha(self):
        self._patch_get(_Resp(200, {"name": "main", "commit": {"sha": "abc123"}}))
        assert _client().get_branch_head("acme/repo", "main") == "abc123"
        assert self.calls == ["https://api.github.com/repos/acme/repo/branches/main"]

    def test_missing_branch_is_none(self):
        self._patch_get(_Resp(404))
        assert _client().get_branch_head("acme/repo", "gone") is None
