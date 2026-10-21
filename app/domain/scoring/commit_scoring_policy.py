from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.scoring.commit_score_value import CommitScoreValue


class CommitScoringPolicy(ABC):
    """How a complete commit's standard runs become its score (strategy)."""

    @abstractmethod
    def score_commit(self, run_results) -> CommitScoreValue: ...
