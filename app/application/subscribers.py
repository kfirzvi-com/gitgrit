"""Domain-event subscribers for the graph feature.

Wires workspace events to background dependency inference. A project's repo is
the source of its dependencies, so the unit of work is per-project; deferring
with a per-project ``queueing_lock`` coalesces rapid changes into one pending
run, and ``lock`` serializes execution so two runs for the same project never
overlap. The defer happens inside the publisher's transaction (Postgres queue),
so it's atomic with the domain write.

Membership *removals* and deletions need no LLM run — the read-time stack-edge
derivation and FK cascade handle them.
"""
from __future__ import annotations

import logging

from procrastinate.exceptions import AlreadyEnqueued

from app.application.event_bus import subscribe
from app.domain.events import (
    ProjectAddedToStack,
    ProjectCreated,
    RepositoryPushed,
)
from app.tasks import infer_project_dependencies

logger = logging.getLogger(__name__)


def _enqueue_dependency_refresh(project_id: str) -> None:
    from app.domain.models import Project

    Project.objects.filter(pk=project_id).update(
        deps_status=Project.DepsStatus.PENDING
    )
    try:
        infer_project_dependencies.configure(
            lock=f"project:{project_id}",
            queueing_lock=f"deps:{project_id}",
        ).defer(project_id=str(project_id))
    except AlreadyEnqueued:
        # A refresh for this project is already queued — coalesced.
        logger.debug("dependency refresh already queued for project %s", project_id)


def _on_project_event(event) -> None:
    _enqueue_dependency_refresh(event.project_id)


def register() -> None:
    """Register subscribers. Called once from AppConfig.ready()."""
    subscribe(ProjectCreated, _on_project_event)
    subscribe(ProjectAddedToStack, _on_project_event)
    subscribe(RepositoryPushed, _on_project_event)
