from __future__ import annotations

from providers.base import BaseProvider


class GitHubProvider(BaseProvider):
    def __init__(self, project_id: str, access_token: str) -> None:
        self.project_id = project_id
        self.access_token = access_token

    def list_files(self) -> list[str]:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_languages(self) -> dict[str, float]:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_members(self) -> list[dict]:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_contributors(self) -> list[dict]:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_default_branch(self) -> str:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_topics(self) -> list[str]:
        raise NotImplementedError("GitHub API integration not yet implemented")

    def get_metadata(self) -> dict:
        raise NotImplementedError("GitHub API integration not yet implemented")
