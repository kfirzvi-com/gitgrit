from __future__ import annotations

from providers.base import BaseProvider


class MockProvider(BaseProvider):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def list_files(self) -> list[str]:
        return [
            "README.md",
            "src/main.py",
            "tests/test_main.py",
            "pyproject.toml",
            ".gitignore",
            "Dockerfile",
            ".github/workflows/ci.yml",
            "docker-compose.yml",
        ]

    def get_languages(self) -> dict[str, float]:
        return {"Python": 72.5, "Dockerfile": 15.0, "YAML": 12.5}

    def get_members(self) -> list[dict]:
        return [
            {"username": "alice", "role": "maintainer"},
            {"username": "bob", "role": "developer"},
        ]

    def get_contributors(self) -> list[dict]:
        return [
            {"username": "alice", "commits": 142},
            {"username": "bob", "commits": 87},
        ]

    def get_default_branch(self) -> str:
        return "main"

    def get_topics(self) -> list[str]:
        return ["python", "backend", "api"]

    def get_metadata(self) -> dict:
        return {
            "name": "mock-project",
            "description": "A mock project for testing",
            "web_url": "https://example.com/mock-project",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-06-01T00:00:00Z",
        }
