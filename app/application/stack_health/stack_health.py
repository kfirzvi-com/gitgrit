from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Max

from app.application.project_health_counts import ProjectHealthCounts
from app.application.stack_health.project_health import ProjectHealth
from app.domain.models import Project, Standard
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class StackHealth:
    """A stack's projects counted by health (never one grade for the stack),
    each worst first, the standards its projects use, and its map's state."""

    stack: object
    health: ProjectHealthCounts
    projects: tuple = field(default_factory=tuple)  # (ProjectHealth, ...)
    project_count: int = 0
    standard_count: int = 0
    map_updated_at: object = None
    map_refreshing: bool = False

    @classmethod
    def of(cls, stack) -> "StackHealth":
        projects = list(
            Project.objects.filter(tenant=stack.tenant, stacks=stack).select_related("platform_connection")
        )
        health = ProjectHealthCounts.of(projects)
        health_of = {
            project.pk: (tone, score)
            for tone in (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)
            for project, score in health.projects_with(tone)
        }
        rows = [ProjectHealth(p, *health_of.get(p.pk, (ScoreTone.UNKNOWN, None))) for p in projects]
        rows.sort(key=lambda r: (-r.tone.severity, r.project.name.lower()))
        mapped = Project.objects.filter(pk__in=[p.pk for p in projects])
        return cls(
            stack=stack,
            health=health,
            projects=tuple(rows),
            project_count=len(projects),
            standard_count=Standard.objects.filter(tenant=stack.tenant, enabled=True, projects__in=projects)
            .distinct()
            .count(),
            map_updated_at=mapped.aggregate(latest=Max("deps_analyzed_at"))["latest"],
            map_refreshing=mapped.filter(
                deps_status__in=(Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)
            ).exists(),
        )
