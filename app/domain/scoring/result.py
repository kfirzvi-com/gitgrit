from __future__ import annotations

from dataclasses import dataclass

from app.domain.importance import Importance
from app.domain.scoring.status import ERROR, FAILED, FINISHED


@dataclass(frozen=True)
class Result:
    """One standard's result on a commit. ``execution_id`` names the run it
    came from, so a score can say what it was computed from."""

    standard_id: str
    name: str
    status: str
    score: int
    importance: Importance = Importance.MAJOR
    execution_id: str = ""

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

    @property
    def fails_commit(self) -> bool:
        """A Required standard that did not pass."""
        return self.importance is Importance.REQUIRED and self.status in (FAILED, ERROR)
