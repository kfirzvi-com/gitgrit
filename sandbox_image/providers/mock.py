from __future__ import annotations

from providers.base import BaseProvider


_DEFAULT_FILES = [
    "README.md",
    "src/main.py",
    "tests/test_main.py",
    "pyproject.toml",
    ".gitignore",
    "Dockerfile",
    ".github/workflows/ci.yml",
    "docker-compose.yml",
]
_DEFAULT_LANGUAGES = {"Python": 72.5, "Dockerfile": 15.0, "YAML": 12.5}
_DEFAULT_MEMBERS = [
    {"username": "alice", "role": "maintainer"},
    {"username": "bob", "role": "developer"},
]
_DEFAULT_CONTRIBUTORS = [
    {"username": "alice", "commits": 142},
    {"username": "bob", "commits": 87},
]
_DEFAULT_TOPICS = ["python", "backend", "api"]
_DEFAULT_METADATA = {
    "name": "mock-project",
    "description": "A mock project for testing",
    "web_url": "https://example.com/mock-project",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-06-01T00:00:00Z",
}


class MockProvider(BaseProvider):
    def __init__(self, project_id: str, data: dict | None = None) -> None:
        self.project_id = project_id
        self._data = data or {}

    def get_file_content(self, path: str) -> str | None:
        file_contents = self._data.get("get_file_content", {})
        return file_contents.get(path)

    def list_files(self) -> list[str]:
        return self._data.get("list_files", _DEFAULT_FILES)

    def get_languages(self) -> dict[str, float]:
        return self._data.get("get_languages", _DEFAULT_LANGUAGES)

    def get_members(self) -> list[dict]:
        return self._data.get("get_members", _DEFAULT_MEMBERS)

    def get_contributors(self) -> list[dict]:
        return self._data.get("get_contributors", _DEFAULT_CONTRIBUTORS)

    def get_default_branch(self) -> str:
        return self._data.get("get_default_branch", "main")

    def get_topics(self) -> list[str]:
        return self._data.get("get_topics", _DEFAULT_TOPICS)

    def get_metadata(self) -> dict:
        return self._data.get("get_metadata", _DEFAULT_METADATA)

    def get_file_last_commit_date(self, path: str) -> str | None:
        commit_dates = self._data.get("get_file_last_commit_date", {})
        return commit_dates.get(path)
