"""A project rooted inside a monorepo sees its own directory as the repository.

Standards are written against repository-relative paths (``package.json``,
``Dockerfile``). For a project at ``apps/web`` those mean
``apps/web/package.json``: this provider prefixes every path it is asked
about with the root and lists only the files under it, stripped of the root.
Repository-wide facts (members, topics, default branch) pass through; the
languages are counted from the project's own files.
"""
from __future__ import annotations

from providers.base import BaseProvider
from providers.languages import language_shares


class RootedProvider(BaseProvider):
    def __init__(self, repository: BaseProvider, root_path: str) -> None:
        self.repository = repository
        self.root_path = root_path.strip("/")
        self._files: list[str] | None = None

    def _in_repository(self, path: str) -> str:
        path = path.strip().lstrip("/")
        return f"{self.root_path}/{path}" if path else self.root_path

    def list_files(self) -> list[str]:
        if self._files is None:
            prefix = self.root_path + "/"
            self._files = [
                p[len(prefix):] for p in self.repository.list_files() if p.startswith(prefix)
            ]
        return self._files

    def get_file_content(self, path: str) -> str | None:
        return self.repository.get_file_content(self._in_repository(path))

    def get_file_size(self, path: str) -> int | None:
        return self.repository.get_file_size(self._in_repository(path))

    def get_file_last_commit_date(self, path: str) -> str | None:
        return self.repository.get_file_last_commit_date(self._in_repository(path))

    def get_languages(self) -> dict[str, float]:
        return language_shares(self.list_files())

    def get_metadata(self) -> dict:
        return {**self.repository.get_metadata(), "root_path": self.root_path}

    def get_members(self) -> list[dict]:
        return self.repository.get_members()

    def get_contributors(self) -> list[dict]:
        return self.repository.get_contributors()

    def get_default_branch(self) -> str:
        return self.repository.get_default_branch()

    def get_topics(self) -> list[str]:
        return self.repository.get_topics()
