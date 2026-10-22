from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring import CommitStanding


@dataclass(frozen=True)
class NewerCommit:
    """A commit newer than the one with the branch's verdict, with none of
    its own: still checking, or no score (``standing.reason``: "License
    errored", "Lint not run")."""

    sha: str
    standing: CommitStanding
