from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommitState:
    """Where a commit stands, by its newest check: ``complete`` (that check
    scored it), ``in_progress`` (a run on the commit is still going) or
    ``incomplete`` (it finished without every expected standard).
    ``expected`` and ``finished`` count that check's standards."""

    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    INCOMPLETE = "incomplete"

    state: str
    expected: int
    finished: int
