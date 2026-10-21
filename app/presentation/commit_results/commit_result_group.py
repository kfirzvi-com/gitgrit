from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommitResultGroup:
    """One group of a commit's standard runs on the Results tab: ``key``
    (running, failed, passed), its heading, and its runs in display order."""

    key: str
    heading: str
    runs: list = field(default_factory=list)
