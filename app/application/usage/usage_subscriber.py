from __future__ import annotations

from app.application.event_bus import subscribe
from app.application.usage.usage_meter import UsageMeter
from app.domain.events import ProjectCreated, StandardRunsQueued, StandardRunTimed
from app.domain.models import Project


class UsageSubscriber:
    """Meters a workspace's usage from the domain events that carry it: new
    projects, queued runs and the sandbox time each run took. The code that
    adds projects and runs standards publishes; it never knows about usage."""

    @staticmethod
    def on_project_created(event: ProjectCreated) -> None:
        UsageMeter.record_projects(event.tenant_id)

    @staticmethod
    def on_runs_queued(event: StandardRunsQueued) -> None:
        project = Project.objects.filter(pk=event.project_id).first()
        if project:
            UsageMeter.record_executions(project, event.count, event.trigger)

    @staticmethod
    def on_run_timed(event: StandardRunTimed) -> None:
        project = Project.objects.filter(pk=event.project_id).first()
        if project:
            UsageMeter.record_run_time(project, event.trigger, event.run_ms)

    @classmethod
    def register(cls) -> None:
        subscribe(ProjectCreated, cls.on_project_created)
        subscribe(StandardRunsQueued, cls.on_runs_queued)
        subscribe(StandardRunTimed, cls.on_run_timed)
