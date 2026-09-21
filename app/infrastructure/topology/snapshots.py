"""``RepositorySnapshot`` adapters."""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.platform_client import get_platform_client

_SKIP_DIRS = {".git"}


class PlatformSnapshot:
    """A repository as the GitHub/GitLab API shows it at one ref."""

    def __init__(self, client, full_path: str, ref: str = ""):
        self._client = client
        self._full_path = full_path
        self._ref = ref

    def list_files(self) -> list[str]:
        return list(self._client.get_tree(self._full_path, self._ref) or [])

    def read_file(self, path: str) -> str | None:
        return self._client.get_file_content(self._full_path, path, self._ref)


def snapshot_for_project(project) -> PlatformSnapshot:
    """The production snapshot: the project's connection, scoped to its repo."""
    client = get_platform_client(project.platform_connection)
    # Route through the auth-method seam, scoping a GitHub App installation
    # token to this project's repository. PAT connections return the stored
    # token unchanged, so their behavior is identical.
    client.token = project.platform_connection.get_access_token(
        repositories=[project.full_path]
    )
    return PlatformSnapshot(client, project.full_path, project.default_branch)


class LocalDirSnapshot:
    """A checkout on disk, for local development and evaluation without a
    platform connection: ``refresh_project_deps --local-path ../repo``."""

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise FileNotFoundError(f"{self._root} is not a directory")

    def list_files(self) -> list[str]:
        out: list[str] = []
        for p in sorted(self._root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self._root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            out.append(rel.as_posix())
        return out

    def read_file(self, path: str) -> str | None:
        target = (self._root / path).resolve()
        if self._root not in target.parents or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None
