from __future__ import annotations

from dataclasses import dataclass

from app.domain.importance import Importance
from app.domain.scoring.standard_run_status import StandardRunStatus


@dataclass(frozen=True)
class StandardRunResult:
    """One standard's run on a commit: its status, the standard's own 0-100
    score (``standard_score``) and the importance the standard had on the
    project when it ran. ``execution_id`` names the run, so a commit score
    can say which runs it was computed from."""

    standard_id: str
    standard_name: str
    status: StandardRunStatus
    standard_score: int
    importance: Importance = Importance.MAJOR
    execution_id: str = ""

    @property
    def is_finished(self) -> bool:
        return StandardRunStatus(self.status).is_finished

    @property
    def fails_the_commit(self) -> bool:
        """A Required standard that failed or errored."""
        return self.importance is Importance.REQUIRED and self.status in (
            StandardRunStatus.FAILED,
            StandardRunStatus.ERROR,
        )
