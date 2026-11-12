from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from app.application import scoring
from app.application.cockpit.attention_row import AttentionRow
from app.application.cockpit.warning_light import WarningLight
from app.application.project_health_counts import ProjectHealthCounts
from app.application.standard_results import current_results
from app.domain.models import CommitCheck, Component, Project, StandardExecution
from app.domain.score_representation import ScoreTone
from app.domain.scoring import CommitScoreOutcome

Status = StandardExecution.Status


@dataclass(frozen=True)
class Cockpit:
    """A workspace's cockpit, read from each project's current results
    (``standard_results.current_results``) with that project's own
    importance for each standard:

    - ``health``: the projects counted failed / need attention / healthy;
    - ``lights``: one lamp per kind of trouble, worst first: a Required
      standard failed, a grade below A, no score;
    - ``rows``: the projects that need you, failed first, each worst first,
      with what pulls them down;
    - ``last_check``: the newest of the scores the counts read, so it says
      how fresh the numbers are;
    - ``checks_by_week``: commits checked in each of the last four weeks
      (rolling seven days), this week first."""

    health: ProjectHealthCounts
    lights: tuple = field(default_factory=tuple)
    rows: tuple = field(default_factory=tuple)
    last_check: object = None  # CommitScore | None
    checks_by_week: tuple = (0, 0, 0, 0)

    @property
    def checks_this_week(self) -> int:
        return self.checks_by_week[0]

    @property
    def checks_last_week(self) -> int:
        return self.checks_by_week[1]

    @property
    def checks_peak(self) -> int:
        """The busiest of the four weeks."""
        return max(self.checks_by_week)

    @classmethod
    def for_workspace(cls, tenant) -> "Cockpit":
        projects = list(Project.objects.filter(tenant=tenant))
        project_scores = scoring.project_scores(projects)
        health = ProjectHealthCounts.of(projects, project_scores)
        results = current_results(projects)

        below_par = defaultdict(list)
        for ex in results:
            if ex.status == Status.FAILED and not ex.fails_the_commit:
                below_par[ex.project_id].append(ex)

        stacks = cls._stacks_by_project(tenant)
        failed = {p.pk for p, _ in health.failed_projects}
        rows = tuple(
            AttentionRow(
                project=project,
                score=score,
                tone=ScoreTone.FAILED if project.pk in failed else ScoreTone.NEEDS_ATTENTION,
                below_par=tuple(
                    ex.standard_name for ex in sorted(below_par[project.pk], key=lambda ex: (ex.score, ex.standard_name))
                ),
                stacks=stacks.get(project.pk, ()),
            )
            for project, score in health.attention
        )

        return cls(
            health=health,
            lights=cls._lights(health),
            rows=rows,
            last_check=max(project_scores.values(), key=lambda s: s.created_at, default=None),
            checks_by_week=cls._checks_by_week(tenant),
        )

    @staticmethod
    def _lights(health) -> tuple:
        """Need attention splits in two: graded B to D, and no score (a
        standard errored or never ran, or never checked)."""
        graded = sum(
            1 for _, score in health.needs_attention_projects
            if score is not None and score.outcome != CommitScoreOutcome.NO_SCORE
        )
        return (
            WarningLight("failed", "Required standard failed", health.failed, ScoreTone.FAILED),
            WarningLight("below_a", "Grade below A", graded, ScoreTone.NEEDS_ATTENTION),
            WarningLight("no_score", "No score", health.needs_attention - graded, ScoreTone.NEEDS_ATTENTION),
        )

    @staticmethod
    def _checks_by_week(tenant, weeks: int = 4) -> tuple:
        now = timezone.now()
        times = CommitCheck.objects.filter(
            project__tenant=tenant, created_at__gte=now - timedelta(weeks=weeks)
        ).values_list("created_at", flat=True)
        counts = [0] * weeks
        for at in times:
            counts[min(int((now - at) / timedelta(weeks=1)), weeks - 1)] += 1
        return tuple(counts)

    @staticmethod
    def _stacks_by_project(tenant) -> dict:
        """Each project's stack names, sorted, once each."""
        by_project = defaultdict(set)
        rows = Component.objects.filter(tenant=tenant, stacks__isnull=False).values_list("project_id", "stacks__name")
        for project_id, name in rows:
            by_project[project_id].add(name)
        return {pid: tuple(sorted(names, key=str.lower)) for pid, names in by_project.items()}
