from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.commit_score_outcome import CommitScoreOutcome


@dataclass(frozen=True)
class CommitScoreValue:
    """A commit's computed score: ``value`` 0-100, or None when a Required
    standard failed it (a verdict, not a number) or when no run could be
    averaged (every one errored); whether a Required standard failed it and
    why."""

    value: int | None
    failed_by_required_standard: bool = False
    failure_reason: str = ""

    def __post_init__(self):
        if self.failed_by_required_standard and self.value is not None:
            raise ValueError("A commit a Required standard failed has no value")

    @property
    def outcome(self) -> CommitScoreOutcome:
        return CommitScoreOutcome.of(self.value, self.failed_by_required_standard)
