from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import StandardExecution
from app.domain.scoring import CommitScoreOutcome, CommitStanding, ExpectedStandards

Status = StandardExecution.Status


@dataclass(frozen=True)
class CheckRun:
    """One check of a commit: one run of the standards on it, as the Results
    tab's timeline shows it. ``executions`` are its own runs, newest first;
    ``standing`` its outcome (``scoring.ScorableCommitCheck.standing``), which
    is its commit's when it is the commit's newest; ``score`` the CommitScore
    it saved (None while running); ``never_ran`` the Standards it expected
    that never ran in it, when the Results tab names them. A branch reads its
    newest commit's newest CheckRun (``scoring.branch_head``)."""

    check: object
    executions: tuple
    standing: CommitStanding | None
    score: object = None
    never_ran: tuple = ()

    @property
    def sha(self) -> str:
        return self.check.commit_sha

    @property
    def outcome(self) -> CommitScoreOutcome | None:
        return self.standing.outcome if self.standing else None

    @property
    def checking(self) -> bool:
        return self.outcome is CommitScoreOutcome.CHECKING

    @property
    def expected(self) -> ExpectedStandards:
        return ExpectedStandards(tuple(self.check.expected_standard_ids))

    @property
    def latest_runs(self) -> list:
        """Its newest run of each standard it expects
        (``ExpectedStandards.lists_runs_of``), running ones included."""
        expected = self.expected
        seen, latest = set(), []
        for ex in self.executions:
            # Runs of standards deleted before archiving existed have no
            # standard left; tell them apart by name.
            key = ex.standard_id or ex.standard_name
            if key in seen or not expected.lists_runs_of(ex.standard_id):
                continue
            seen.add(key)
            latest.append(ex)
        return latest

    @property
    def never_ran_ids(self) -> list[str]:
        """The standards it expected that never ran in it."""
        if not self.expected:
            return []
        return self.expected.without_any_run(ex.standard_id for ex in self.executions)
