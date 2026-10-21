from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring import CommitScoringState


@dataclass(frozen=True)
class NewerCommit:
    """A commit newer than the scored one on the branch, not scored (yet)."""

    sha: str
    state: CommitScoringState
