from enum import StrEnum


class StandardRunStatus(StrEnum):
    """The status of one standard's run on a commit, as stored on
    ``StandardExecution.status``."""

    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def is_finished(self) -> bool:
        """The run is over with an outcome: it passed, failed or errored."""
        return self in (StandardRunStatus.PASSED, StandardRunStatus.FAILED, StandardRunStatus.ERROR)
