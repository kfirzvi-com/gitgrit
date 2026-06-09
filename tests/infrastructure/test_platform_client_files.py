import base64
from types import SimpleNamespace

from app.infrastructure.platform_client import GitHubClient


class _Resp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


def _client():
    return GitHubClient(
        SimpleNamespace(base_url="https://api.github.com", access_token="t")
    )


def test_get_tree_returns_blob_paths(monkeypatch):
    def fake_get(url, **kw):
        assert url.endswith("/repos/org/repo/git/trees/main")
        return _Resp(json_data={"tree": [
            {"path": "go.mod", "type": "blob"},
            {"path": "src", "type": "tree"},
            {"path": "src/main.go", "type": "blob"},
        ]})

    monkeypatch.setattr("app.infrastructure.platform_client.requests.get", fake_get)
    assert _client().get_tree("org/repo", "main") == ["go.mod", "src/main.go"]


def test_get_file_content_decodes_base64(monkeypatch):
    payload = base64.b64encode(b"hello: world\n").decode()

    def fake_get(url, **kw):
        return _Resp(json_data={"type": "file", "encoding": "base64", "content": payload})

    monkeypatch.setattr("app.infrastructure.platform_client.requests.get", fake_get)
    assert _client().get_file_content("org/repo", "config.yaml", "main") == "hello: world\n"


def test_get_file_content_missing_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.platform_client.requests.get",
        lambda url, **kw: _Resp(status=404),
    )
    assert _client().get_file_content("org/repo", "nope.txt", "main") is None


def test_get_file_content_directory_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.platform_client.requests.get",
        lambda url, **kw: _Resp(json_data=[{"name": "a"}, {"name": "b"}]),
    )
    assert _client().get_file_content("org/repo", "src", "main") is None
