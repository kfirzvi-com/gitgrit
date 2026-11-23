"""Where a project starts inside its git repository.

A project is a repository, or a directory inside one: a monorepo holds one
project per app, service or library, each with its own standards, checks and
score. ``RootPath`` is that directory, repository-relative and normalised:
no leading or trailing slash, ``""`` for the whole repository.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

MAX_LENGTH = 1024


class InvalidRootPath(ValueError):
    """A root path that cannot name a directory inside the repository."""


@dataclass(frozen=True)
class RootPath:
    value: str = ""

    @classmethod
    def parse(cls, raw: str | None) -> RootPath:
        """Normalise user input (``"/apps/web/"``, ``"apps\\web"``, ``"./apps/web"``)
        to ``apps/web``. Raises ``InvalidRootPath`` for ``..``, absolute
        Windows paths and over-long values."""
        text = (raw or "").strip().replace("\\", "/")
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise InvalidRootPath("A root path cannot leave the repository (no '..').")
        if parts and parts[0].endswith(":"):
            raise InvalidRootPath("A root path is relative to the repository root.")
        value = "/".join(parts)
        if len(value) > MAX_LENGTH:
            raise InvalidRootPath(f"A root path is at most {MAX_LENGTH} characters.")
        return cls(value)

    @property
    def is_repository_root(self) -> bool:
        return self.value == ""

    def contains(self, repo_path: str) -> bool:
        """Is the repository-relative ``repo_path`` inside this root?"""
        if self.is_repository_root:
            return True
        path = repo_path.strip("/")
        return path == self.value or path.startswith(self.value + "/")

    def covers(self, changed_paths: Iterable[str] | None) -> bool:
        """Does a change touching ``changed_paths`` concern a project rooted
        here? The repository root covers every change. ``None`` means the
        changed files are unknown, which covers everything too: running a
        project needlessly is safer than missing a change."""
        if self.is_repository_root or changed_paths is None:
            return True
        return any(self.contains(p) for p in changed_paths)

    def to_repository(self, project_path: str) -> str:
        """A project-relative path as a repository-relative one."""
        path = project_path.strip("/")
        if self.is_repository_root:
            return path
        return f"{self.value}/{path}" if path else self.value

    def to_project(self, repo_path: str) -> str | None:
        """A repository-relative path as a project-relative one, or ``None``
        when it lies outside this root."""
        path = repo_path.strip("/")
        if self.is_repository_root:
            return path
        if path == self.value:
            return ""
        prefix = self.value + "/"
        return path[len(prefix):] if path.startswith(prefix) else None

    def __str__(self) -> str:
        return self.value
