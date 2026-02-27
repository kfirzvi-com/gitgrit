from __future__ import annotations

from providers.base import BaseProvider
from providers.github import GitHubProvider
from providers.gitlab import GitLabProvider
from providers.mock import MockProvider


def create_provider(
    platform: str,
    project_id: str,
    access_token: str | None,
    base_url: str = "",
    full_path: str = "",
) -> BaseProvider:
    if access_token is None or platform == "mock":
        return MockProvider(project_id)
    if platform == "github":
        return GitHubProvider(project_id, access_token, base_url=base_url, full_path=full_path)
    if platform == "gitlab":
        return GitLabProvider(project_id, access_token)
    raise ValueError(f"Unknown platform: {platform}")
