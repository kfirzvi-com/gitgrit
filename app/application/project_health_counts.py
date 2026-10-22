"""How many projects are failed, need attention, healthy or have no data,
each from its own commit score. Never one grade or colour for many
projects: the dashboard and every stack show these counts instead."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.application import scoring
from app.domain.health import project_level
from app.domain.models import Project
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ProjectHealthCounts:
    """Projects counted by their health (``ScoreHealth`` of each project's
    score): failed (a Required standard failed), needs attention (B to D),
    healthy (A+, A), no data (no score yet). ``attention`` lists the
    projects that are failed or need attention, with their scores, failed
    first then lowest: each one as itself, never combined."""

    failed: int
    needs_attention: int
    healthy: int
    no_data: int
    attention: tuple = ()  # ((project, CommitScore), ...)

    @classmethod
    def of(cls, projects, project_scores=None) -> "ProjectHealthCounts":
        """``projects`` counted; ``project_scores`` (project id -> score)
        when already read, else read here."""
        projects = list(projects)
        if project_scores is None:
            project_scores = scoring.project_scores(projects)
        scored = [(p, project_scores.get(p.pk)) for p in projects]
        health = {p.pk: cls.project_health(s) for p, s in scored}
        counts = Counter(health.values())
        attention = sorted(
            ((p, s) for p, s in scored if health[p.pk].needs_attention),
            key=lambda t: (not t[1].failed, t[1].value if t[1].value is not None else 0, t[0].name.lower()),
        )
        return cls(
            failed=counts[ScoreTone.FAILED],
            needs_attention=counts[ScoreTone.NEEDS_ATTENTION],
            healthy=counts[ScoreTone.HEALTHY],
            no_data=counts[ScoreTone.UNKNOWN],
            attention=tuple(attention),
        )

    @classmethod
    def for_workspace(cls, tenant) -> "ProjectHealthCounts":
        return cls.of(Project.objects.filter(tenant=tenant))

    @staticmethod
    def project_health(commit_score) -> ScoreTone:
        """A project's health from its commit score (``ScoreHealth``)."""
        if commit_score is None:
            return project_level(None)
        return project_level(commit_score.value, failed=commit_score.failed)

    def as_dict(self) -> dict:
        """The counts, for the diagrams."""
        return {
            "failed": self.failed,
            "needs_attention": self.needs_attention,
            "healthy": self.healthy,
            "no_data": self.no_data,
        }
