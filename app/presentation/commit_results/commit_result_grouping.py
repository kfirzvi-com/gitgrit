from __future__ import annotations

from app.domain.importance import Importance
from app.domain.scoring import StandardRunStatus
from app.presentation.commit_results.commit_result_group import CommitResultGroup


class CommitResultGrouping:
    """How a commit's standard runs are laid out on the Results tab, worst
    first: still running, then failed, then could not run (an error is not a
    failure), then passed. Within each group, by the importance the run ran
    with (Required, Major, Minor), then in failed the lowest score; then by
    name. Empty groups are left out. A standard whose importance changed
    later keeps its place on an old commit."""

    @classmethod
    def of(cls, runs) -> list[CommitResultGroup]:
        runs = list(runs)
        running = [r for r in runs if r.status == StandardRunStatus.RUNNING]
        failed = [r for r in runs if r.status == StandardRunStatus.FAILED]
        could_not_run = [r for r in runs if r.status == StandardRunStatus.ERROR]
        passed = [r for r in runs if r.status == StandardRunStatus.PASSED]
        groups = [
            CommitResultGroup("running", "Running", sorted(running, key=cls._by_importance)),
            CommitResultGroup("failed", "Failed", sorted(failed, key=cls._worst_first)),
            CommitResultGroup("could_not_run", "Could not run", sorted(could_not_run, key=cls._by_importance)),
            CommitResultGroup("passed", "Passed", sorted(passed, key=cls._by_importance)),
        ]
        return [group for group in groups if group.runs]

    # Most important first: the order Importance declares them in.
    IMPORTANCE_ORDER = {importance.value: rank for rank, importance in enumerate(Importance)}

    @classmethod
    def _importance_rank(cls, run) -> int:
        return cls.IMPORTANCE_ORDER.get(run.importance, len(cls.IMPORTANCE_ORDER))

    @classmethod
    def _worst_first(cls, run):
        return (cls._importance_rank(run), run.score, run.standard_name.lower())

    @classmethod
    def _by_importance(cls, run):
        return (cls._importance_rank(run), run.standard_name.lower())
