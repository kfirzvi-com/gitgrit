from __future__ import annotations

from enum import StrEnum


class CommitScoreOutcome(StrEnum):
    """A commit's one outcome, decided in this order:

    - ``CHECKING``: a run on the commit is still going: no verdict yet.
    - ``NO_SCORE``: an expected standard has no result, because it errored
      or never ran (Required ones too): nothing is reported.
    - ``FAILED``: every standard ran and a Required one failed. A verdict,
      not a number: the commit has no value.
    - ``SCORED``: every standard ran and no Required one failed: the
      importance-weighted average, 0 to 100, even 0."""

    CHECKING = "checking"
    NO_SCORE = "no_score"
    FAILED = "failed"
    SCORED = "scored"

    @classmethod
    def of(cls, value, failed: bool) -> "CommitScoreOutcome":
        """The outcome a saved score holds (a saved score is never CHECKING)."""
        if failed:
            return cls.FAILED
        return cls.NO_SCORE if value is None else cls.SCORED

    @classmethod
    def of_commit(cls, any_run_going: bool, saved: "CommitScoreOutcome | None") -> "CommitScoreOutcome | None":
        """A commit's outcome: checking while any run on it is going (even
        when an earlier check already decided it), otherwise what its newest
        saved score says; None before it has one."""
        return cls.CHECKING if any_run_going else saved

    @property
    def is_verdict(self) -> bool:
        """An F or a number: what a branch and a project show. A commit that
        is checking or has no score never hides an earlier verdict."""
        return self in (CommitScoreOutcome.FAILED, CommitScoreOutcome.SCORED)
