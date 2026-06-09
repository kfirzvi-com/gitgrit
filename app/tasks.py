"""Background tasks (Procrastinate, Postgres-backed).

Registered at startup via ``AppConfig.ready`` so the worker
(``manage.py procrastinate worker``) and deferring code both see them.
"""
from __future__ import annotations

import logging

from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)


@app.task(queue="graph", name="infer_project_dependencies", retry=2)
def infer_project_dependencies(project_id: str) -> None:
    """Analyze one project's repo and (re)write its dependency edges.

    Idempotent: re-running replaces the project's edges. Deferred with a
    per-project ``queueing_lock`` (coalesce) + ``lock`` (serialize) — see
    ``app.application.subscribers``.
    """
    # Imported lazily so task registration doesn't pull in Django models at
    # import time (the worker imports this module early).
    from app.application.dependency_agent import infer_and_store
    from app.domain.models import Project

    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        logger.warning("infer_project_dependencies: project %s no longer exists", project_id)
        return

    Project.objects.filter(pk=project_id).update(
        deps_status=Project.DepsStatus.RUNNING, deps_error=""
    )
    try:
        infer_and_store(project)
    except Exception as exc:
        logger.exception("dependency inference failed for project %s", project_id)
        Project.objects.filter(pk=project_id).update(
            deps_status=Project.DepsStatus.FAILED, deps_error=str(exc)[:2000]
        )
        raise  # surface to Procrastinate so it can retry
