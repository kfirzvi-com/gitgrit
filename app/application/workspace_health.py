"""How many of a workspace's projects are healthy, need attention or
failed, from each project's commit score: the dashboard's summary."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.application import scoring
from app.domain.health import project_level
from app.domain.models import Project
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class WorkspaceHealth:
    """Projects counted by health (``ScoreHealth`` of each project's score):
    failed (a Required standard failed), needs attention (B to D), healthy
    (A+, A), and no data (no score yet)."""

    failed: int
    needs_attention: int
    healthy: int
    no_data: int

    @classmethod
    def of(cls, tenant) -> "WorkspaceHealth":
        projects = list(Project.objects.filter(tenant=tenant))
        scores = scoring.project_scores(projects)
        counts = Counter(
            project_level(score.value, failed=score.failed) if score else ScoreTone.UNKNOWN
            for score in (scores.get(p.pk) for p in projects)
        )
        return cls(
            failed=counts[ScoreTone.FAILED],
            needs_attention=counts[ScoreTone.NEEDS_ATTENTION],
            healthy=counts[ScoreTone.HEALTHY],
            no_data=counts[ScoreTone.UNKNOWN],
        )
