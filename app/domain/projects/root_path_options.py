"""The directories offered when picking a project's root path.

Every directory of the repository is a valid root path, but in a monorepo the
useful ones are where an app, service or library starts: a directory holding
a build manifest. Those come first, named by their manifest; the other
directories follow so any path can still be picked.
"""
from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass

# A file that marks the directory holding it as something built on its own.
MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "mix.exs",
    "Dockerfile",
    "main.tf",
    "Chart.yaml",
)
# Directories nobody roots a project in.
_SKIPPED = {"node_modules", "vendor", "dist", "build", "target", "__pycache__", "venv", ".venv"}
MAX_DEPTH = 4
MAX_OPTIONS = 300


@dataclass(frozen=True)
class RootPathOption:
    path: str
    manifests: tuple[str, ...] = ()

    @property
    def is_project_like(self) -> bool:
        return bool(self.manifests)


class RootPathOptions:
    """The root paths a repository offers, from its file paths."""

    def __init__(self, files: Iterable[str], taken: Iterable[str] = ()):
        self._files = files
        self._taken = set(taken)

    def options(self) -> list[RootPathOption]:
        manifests: dict[str, list[str]] = {}
        directories: set[str] = set()
        for path in self._files:
            parts = path.strip("/").split("/")
            folders = parts[:-1]
            if any(p.startswith(".") or p in _SKIPPED for p in folders):
                continue
            for depth in range(1, min(len(folders), MAX_DEPTH) + 1):
                directories.add("/".join(folders[:depth]))
            name = parts[-1]
            if folders and len(folders) <= MAX_DEPTH and name in MANIFESTS:
                manifests.setdefault(posixpath.dirname(path.strip("/")), []).append(name)
        open_ = sorted(d for d in directories if d not in self._taken)
        options = [RootPathOption(d, tuple(sorted(manifests.get(d, [])))) for d in open_]
        options.sort(key=lambda o: (not o.is_project_like, o.path))
        return options[:MAX_OPTIONS]
