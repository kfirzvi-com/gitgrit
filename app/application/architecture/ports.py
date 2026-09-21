"""Ports the architecture use cases depend on.

The core defines what it needs; adapters in ``app.infrastructure.topology``
plug in: a snapshot backed by the GitHub/GitLab API or by a directory on disk,
an inference backed by an LLM or by a fixture file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.domain.architecture.resolve import RosterEntry
from app.domain.architecture.topology import RepositoryTopology


class RepositorySnapshot(Protocol):
    """Read-only view of one repository at one revision."""

    def list_files(self) -> list[str]:
        """Every file path in the repository, repository-relative, ``/``-separated."""
        ...

    def read_file(self, path: str) -> str | None:
        """The file's text, or None when it is missing or not text."""
        ...


@dataclass(frozen=True)
class InferenceContext:
    """What an inference needs to know besides the repository itself."""

    project_name: str
    full_path: str
    roster: tuple[RosterEntry, ...] = ()
    log: Callable[[str], None] = field(default=lambda message: None)


class TopologyInference(Protocol):
    """Produces a repository's topology from a snapshot."""

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        ...
