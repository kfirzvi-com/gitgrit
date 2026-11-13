from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Max

from app.application.project_health_counts import ProjectHealthCounts
from app.application.stack_health.component_health import ComponentHealth
from app.domain.models import Component, Project, Standard
from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class StackHealth:
    """A stack's projects counted by health (never one grade for the stack),
    its components worst first, the standards its projects use, and its
    map's state."""

    stack: object
    health: ProjectHealthCounts
    components: tuple = field(default_factory=tuple)  # (ComponentHealth, ...)
    project_count: int = 0
    standard_count: int = 0
    map_updated_at: object = None
    map_refreshing: bool = False

    @classmethod
    def of(cls, stack) -> "StackHealth":
        components = list(
            Component.objects.filter(tenant=stack.tenant, stacks=stack).select_related(
                "project", "project__platform_connection"
            )
        )
        projects = list({c.project_id: c.project for c in components}.values())
        health = ProjectHealthCounts.of(projects)
        health_of = {
            project.pk: (tone, score)
            for tone in (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)
            for project, score in health.projects_with(tone)
        }
        rows = [
            ComponentHealth(c, *health_of.get(c.project_id, (ScoreTone.UNKNOWN, None)))
            for c in components
        ]
        rows.sort(key=lambda r: (-r.tone.severity, r.component.name.lower()))
        mapped = Project.objects.filter(pk__in=[p.pk for p in projects])
        return cls(
            stack=stack,
            health=health,
            components=tuple(rows),
            project_count=len(projects),
            standard_count=Standard.objects.filter(tenant=stack.tenant, enabled=True, projects__in=projects)
            .distinct()
            .count(),
            map_updated_at=mapped.aggregate(latest=Max("deps_analyzed_at"))["latest"],
            map_refreshing=mapped.filter(
                deps_status__in=(Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)
            ).exists(),
        )
