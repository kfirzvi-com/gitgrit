from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.commit_score_value import CommitScoreValue


@dataclass(frozen=True)
class NewCommitScore:
    """What a finished, complete commit check produces: the commit's new
    score and the standard runs it was computed from."""

    score: CommitScoreValue
    run_results: list
