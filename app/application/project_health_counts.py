"""How many projects are failed, need attention or are healthy, each from
its own commit score. Never one grade or colour for many projects: the
dashboard and every stack show these counts instead."""
from __future__ import annotations

from dataclasses import dataclass

from app.application import scoring
from app.domain.health import counted_level, project_level
from app.domain.models import Project
from app.domain.score_representation import ScoreTone
from app.domain.scoring import CommitScoreOutcome


@dataclass(frozen=True)
class ProjectHealthCounts:
    """Projects counted by their health (``ScoreHealth`` of each project's
    score, ``health.counted_level``): failed (a Required standard failed),
    needs attention (B to D, and every project with no grade: no score, no
    standards, never checked), healthy (A+, A). ``projects`` holds the
    projects behind each count, with their scores, worst first
    (``_worst_first``: errors, then no score at all, then lowest grades), so
    a count can list them; ``attention`` the failed and
    needing-attention ones, failed first: each one as itself, never
    combined."""

    failed: int
    needs_attention: int
    healthy: int
    projects: dict = None  # {ScoreTone: ((project, CommitScore | None), ...)}

    @property
    def attention(self) -> tuple:
        """The failed projects, then the ones that need attention."""
        projects = self.projects or {}
        return projects.get(ScoreTone.FAILED, ()) + projects.get(ScoreTone.NEEDS_ATTENTION, ())

    def projects_with(self, tone) -> tuple:
        return (self.projects or {}).get(ScoreTone(tone), ())

    # The projects behind each count, for templates.
    @property
    def failed_projects(self) -> tuple:
        return self.projects_with(ScoreTone.FAILED)

    @property
    def needs_attention_projects(self) -> tuple:
        return self.projects_with(ScoreTone.NEEDS_ATTENTION)

    @property
    def healthy_projects(self) -> tuple:
        return self.projects_with(ScoreTone.HEALTHY)

    @classmethod
    def of(cls, projects, project_scores=None) -> "ProjectHealthCounts":
        """``projects`` counted; ``project_scores`` (project id -> score)
        when already read, else read here."""
        projects = list(projects)
        if project_scores is None:
            project_scores = scoring.project_scores(projects)
        by_tone = {tone: [] for tone in (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)}
        for project in projects:
            score = project_scores.get(project.pk)
            by_tone[counted_level(cls.project_health(score))].append((project, score))
        return cls(
            failed=len(by_tone[ScoreTone.FAILED]),
            needs_attention=len(by_tone[ScoreTone.NEEDS_ATTENTION]),
            healthy=len(by_tone[ScoreTone.HEALTHY]),
            projects={tone: tuple(sorted(rows, key=cls._worst_first)) for tone, rows in by_tone.items()},
        )

    @staticmethod
    def _worst_first(row):
        """How a count lists its projects: no score because a standard
        errored or never ran first, then no score at all (no standards, never
        checked, or being checked), then grades, lowest first; then by name."""
        project, score = row
        if score is not None and score.outcome is CommitScoreOutcome.NO_SCORE:
            rank = 0
        elif score is None:
            rank = 1
        else:
            rank = 2
        return (rank, score.value if score and score.value is not None else 0, project.name.lower())

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
        }
