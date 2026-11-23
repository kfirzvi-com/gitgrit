from __future__ import annotations

from providers.base import BaseProvider
from providers.github import GitHubProvider
from providers.gitlab import GitLabProvider
from providers.mock import MockProvider
from providers.artifact import ArtifactProvider
from providers.rooted import RootedProvider


def create_project_provider(root_path: str = "", **kwargs) -> tuple[BaseProvider, BaseProvider]:
    """The provider a standard reads the project through, and the one for its
    whole repository. They are the same unless the project is rooted inside
    the repository (a monorepo app or service)."""
    repository = create_provider(**kwargs)
    root = (root_path or "").strip("/")
    return (RootedProvider(repository, root) if root else repository), repository


def create_provider(
    platform: str,
    project_id: str,
    access_token: str | None,
    base_url: str = "",
    full_path: str = "",
    ref: str = "",
    mock_data: dict | None = None,
) -> BaseProvider:
    # Artifact projects carry no token by design; check before the token-less mock path.
    if platform == "artifact":
        return ArtifactProvider(project_id, full_path=full_path, ref=ref)
    if access_token is None or platform == "mock":
        return MockProvider(project_id, data=mock_data)
    if platform == "github":
        return GitHubProvider(
            project_id, access_token, base_url=base_url, full_path=full_path, ref=ref
        )
    if platform == "gitlab":
        return GitLabProvider(
            project_id, access_token, base_url=base_url, full_path=full_path, ref=ref
        )
    raise ValueError(f"Unknown platform: {platform}")
