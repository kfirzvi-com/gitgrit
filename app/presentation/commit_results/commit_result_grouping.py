from __future__ import annotations

from app.domain.importance import Importance
from app.domain.scoring import StandardRunStatus
from app.presentation.commit_results.commit_result_group import CommitResultGroup


class CommitResultGrouping:
    """How a commit's standard runs are laid out on the Results tab, worst
    first: still running, then failed (failures and errors: Required
    standards first, then failures before errors, then the lowest score),
    then passed (by name). Empty groups are left out. Each run is grouped by
    the importance it ran with, so a standard made Required later does not
    move up on an old commit."""

    @classmethod
    def of(cls, runs) -> list[CommitResultGroup]:
        runs = list(runs)
        running = [r for r in runs if r.status == StandardRunStatus.RUNNING]
        failed = [r for r in runs if r.status in (StandardRunStatus.FAILED, StandardRunStatus.ERROR)]
        passed = [r for r in runs if r.status == StandardRunStatus.PASSED]
        groups = [
            CommitResultGroup("running", "Running", sorted(running, key=cls._by_name)),
            CommitResultGroup("failed", "Failed", sorted(failed, key=cls._worst_first)),
            CommitResultGroup("passed", "Passed", sorted(passed, key=cls._by_name)),
        ]
        return [group for group in groups if group.runs]

    @staticmethod
    def _worst_first(run):
        return (
            run.importance != Importance.REQUIRED,
            run.status != StandardRunStatus.FAILED,
            run.score,
            run.standard_name.lower(),
        )

    @staticmethod
    def _by_name(run):
        return run.standard_name.lower()
