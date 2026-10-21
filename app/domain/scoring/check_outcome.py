from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.score import Score


@dataclass(frozen=True)
class CheckOutcome:
    """A finished, complete check: the commit's new score and the results it
    was computed from."""

    score: Score
    results: list
