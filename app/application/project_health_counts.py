"""How many projects are failed, need attention, healthy or have no data,
each from its own commit score. Never one grade or colour for many
projects: the dashboard and every stack show these counts instead."""
from __future__ import annotations

from dataclasses import dataclass

from app.application import scoring
from app.domain.health import project_level
from app.domain.models import Project
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ProjectHealthCounts:
    """Projects counted by their health (``ScoreHealth`` of each project's
    score): failed (a Required standard failed), needs attention (B to D),
    healthy (A+, A), no data (no score yet). ``projects`` holds the projects
    behind each count, with their scores, lowest first then by name (so a
    count can list them); ``attention`` the failed and needing-attention ones,
    failed first: each one as itself, never combined. Each project carries
    ``newest_without_score``: its newest commit's CommitScore when that
    commit has no score (so its score is an older commit's), else None."""

    failed: int
    needs_attention: int
    healthy: int
    no_data: int
    projects: dict = None  # {ScoreTone: ((project, CommitScore | None), ...)}
    # The projects showing an older commit, because their newest has no
    # score, whatever their health; by name.
    older_commit: tuple = ()

    @property
    def older_commit_names(self) -> list[str]:
        return [p.name for p in self.older_commit]

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

    @property
    def no_data_projects(self) -> tuple:
        return self.projects_with(ScoreTone.UNKNOWN)

    @classmethod
    def of(cls, projects, project_scores=None, without_score=None) -> "ProjectHealthCounts":
        """``projects`` counted; ``project_scores`` (project id -> score)
        and ``without_score`` (``scoring.newest_without_score``) when already
        read, else read here."""
        projects = list(projects)
        if project_scores is None:
            project_scores = scoring.project_scores(projects)
        if without_score is None:
            without_score = scoring.newest_without_score(projects)
        by_tone = {tone: [] for tone in ScoreTone}
        for project in projects:
            project.newest_without_score = without_score.get(project.pk)
            score = project_scores.get(project.pk)
            by_tone[cls.project_health(score)].append((project, score))
        lowest_first = lambda t: (t[1].value if t[1] and t[1].value is not None else 0, t[0].name.lower())  # noqa: E731
        return cls(
            failed=len(by_tone[ScoreTone.FAILED]),
            needs_attention=len(by_tone[ScoreTone.NEEDS_ATTENTION]),
            healthy=len(by_tone[ScoreTone.HEALTHY]),
            no_data=len(by_tone[ScoreTone.UNKNOWN]),
            projects={tone: tuple(sorted(rows, key=lowest_first)) for tone, rows in by_tone.items()},
            older_commit=tuple(sorted((p for p in projects if p.newest_without_score), key=lambda p: p.name.lower())),
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
