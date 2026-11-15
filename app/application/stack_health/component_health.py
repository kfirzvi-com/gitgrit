from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ComponentHealth:
    """One component of a stack with its repository's health and score
    (None when the repository was never checked)."""

    component: object  # Component
    tone: ScoreTone
    score: object = None  # CommitScore | None
