from __future__ import annotations

from dataclasses import dataclass

from app.domain import scoring


@dataclass(frozen=True)
class CheckRunRecord:
    """A check as it is stored, for the screens: its domain ``run``
    (``scoring.CheckRun``, which holds every rule) beside its rows: the
    CommitCheck, its StandardExecutions (newest first), the CommitScore it
    saved (None while running) and, when the Results tab names them, the
    Standards it expected that never ran in it."""

    check: object
    run: scoring.CheckRun
    executions: tuple = ()
    score: object = None
    never_ran: tuple = ()

    @property
    def sha(self) -> str:
        return self.check.commit_sha

    @property
    def standing(self) -> scoring.CommitStanding | None:
        return self.run.standing

    @property
    def outcome(self) -> scoring.CommitScoreOutcome | None:
        return self.run.outcome

    @property
    def checking(self) -> bool:
        return self.outcome is scoring.CommitScoreOutcome.CHECKING

    @property
    def latest_runs(self) -> list:
        """The executions behind ``run.latest_results``, in that order."""
        by_id = {str(ex.pk): ex for ex in self.executions}
        return [by_id[r.execution_id] for r in self.run.latest_results]

    @property
    def never_ran_ids(self) -> list[str]:
        return self.run.never_ran_ids
