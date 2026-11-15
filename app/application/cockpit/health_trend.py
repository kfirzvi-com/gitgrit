from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from app.application.cockpit.trend_point import TrendPoint
from app.application.project_health_counts import ProjectHealthCounts
from app.domain.models import CommitScore, Project
from app.domain.score_representation import ScoreTone


class HealthTrend:
    """Healthy projects week by week: on each day, each project's newest
    score on its default branch as it stood then, read with the same health
    rule as today's counts. A project counts from the day it was added."""

    @staticmethod
    def weekly(tenant, weeks: int = 4, today=None) -> tuple[TrendPoint, ...]:
        today = today or timezone.localdate()
        days = [today - timedelta(weeks=n) for n in range(weeks, -1, -1)]
        projects = list(Project.objects.filter(tenant=tenant).only("pk", "default_branch", "created_at"))
        if not projects:
            return tuple(TrendPoint(day=d, healthy=0, total=0) for d in days)

        default_branch = {p.pk: p.default_branch for p in projects}
        history = defaultdict(list)  # project id -> scores, newest first
        scores = (
            CommitScore.objects.filter(project__in=projects)
            .only("project_id", "branch", "value", "failed", "created_at", "ordered_at")
            .order_by("project_id", "-ordered_at", "-created_at")
        )
        for score in scores:
            if score.branch == default_branch[score.project_id]:
                history[score.project_id].append(score)

        points = []
        for day in days:
            end = timezone.make_aware(timezone.datetime.combine(day + timedelta(days=1), timezone.datetime.min.time()))
            alive = [p for p in projects if p.created_at < end]
            healthy = 0
            for project in alive:
                as_of = next((s for s in history[project.pk] if s.created_at < end), None)
                if as_of is not None and ProjectHealthCounts.project_health(as_of) is ScoreTone.HEALTHY:
                    healthy += 1
            points.append(TrendPoint(day=day, healthy=healthy, total=len(alive)))
        return tuple(points)
