"""A stack's health, from its projects' commit scores: the one rule the
Stacks page and the dashboard diagram both read."""
from __future__ import annotations

from dataclasses import dataclass

from app.application import scoring
from app.domain.health import project_level, stack_level
from app.domain.models import CommitScore
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class StackHealth:
    """A stack is as healthy as its least healthy project: one failed
    project fails the stack's colour, however healthy the rest look.

    ``worst`` is that project's commit score (None when no project has one),
    ``ranked`` every project with its score, least healthy first, and
    ``failed`` how many of them a Required standard failed."""

    worst: CommitScore | None
    tone: ScoreTone
    ranked: list  # [(project, CommitScore | None)], least healthy first
    failed: int

    @classmethod
    def of(cls, projects, project_scores=None) -> "StackHealth":
        """``projects``' health; ``project_scores`` (project id -> score)
        when already read, else read here."""
        projects = list(projects)
        if project_scores is None:
            project_scores = scoring.project_scores(projects)
        ranked = sorted(((p, project_scores.get(p.pk)) for p in projects), key=lambda t: cls.least_healthy_first(t[1]))
        return cls(
            worst=next((s for _, s in ranked if s is not None), None),
            tone=stack_level([cls.project_health(s) for _, s in ranked]),
            ranked=ranked,
            failed=sum(1 for _, s in ranked if s is not None and s.failed),
        )

    @staticmethod
    def project_health(commit_score) -> ScoreTone:
        """A project's health from its commit score (``ScoreHealth``)."""
        if commit_score is None:
            return project_level(None)
        return project_level(commit_score.value, failed=commit_score.failed)

    @classmethod
    def least_healthy_first(cls, commit_score):
        """Sort key: failed, then needing attention by lowest score, then
        healthy, then no score."""
        health = cls.project_health(commit_score)
        value = commit_score.value if commit_score and commit_score.value is not None else 101
        return (-health.severity if health is not ScoreTone.UNKNOWN else 1, value)
