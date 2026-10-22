from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.commit_score_outcome import CommitScoreOutcome


@dataclass(frozen=True)
class CommitStanding:
    """Where a commit stands, by its newest check: its ``outcome`` (checking,
    no score, failed or scored), ``reason`` (why it failed or has no score),
    how many of the standards that check expects have a finished run
    (``finished_count`` of ``expected_count``), and ``value``, 0-100, only
    when scored."""

    outcome: CommitScoreOutcome
    reason: str
    expected_count: int
    finished_count: int
    value: int | None = None
