from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.scoring.commit_score_value import CommitScoreValue


class CommitScoringPolicy(ABC):
    """How a finished commit's standard runs become its score (strategy).
    ``run_results``: each expected standard's newest finished run;
    ``not_run``: the names of the expected standards with no finished run."""

    @abstractmethod
    def score_commit(self, run_results, not_run=()) -> CommitScoreValue: ...
