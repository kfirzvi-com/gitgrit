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
        """A Required standard that ran and failed: it fails the commit, once
        every other expected standard has a result too."""
        return self.importance is Importance.REQUIRED and self.status == StandardRunStatus.FAILED

    @property
    def errored(self) -> bool:
        """It produced no result: the commit has no score."""
        return self.status == StandardRunStatus.ERROR

    @property
    def needs_attention(self) -> bool:
        """What "Needs attention" lists: a run that fails its commit (a
        Required standard that failed) or one that errored (the commit has
        no score). A Major or Minor failure only lowers the score."""
        return self.fails_the_commit or self.errored
