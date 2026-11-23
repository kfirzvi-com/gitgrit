from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ProjectHealth:
    """One project of a stack with its health and score (None when the
    project was never checked)."""

    project: object  # Project
    tone: ScoreTone
    score: object = None  # CommitScore | None
