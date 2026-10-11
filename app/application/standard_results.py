"""Reads of a workspace's current standard results.

"Current" means the latest finished result per (project, standard) for
standards still attached to their project. Every screen that scores projects
or lists problems starts from ``attached_executions``, and every screen that
shows "Needs attention" (the dashboard card, the notifications pane) calls
``attention_items``, so they never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Exists, OuterRef

from app.domain.health import CRITICAL, HEALTHY, WARNING, level_from_score
from app.domain.models import ProjectStandard, StandardExecution

# How far back attention_items looks; plenty to find the latest result of
# every attached pair in a workspace.
_RECENT_EXECUTIONS = 500


def attached_executions(tenant):
    """Tenant executions whose standard is currently attached to their project.

    Detached (or deleted) standards' old executions must not drag project
    scores or raise attention items.
    """
    attached = ProjectStandard.objects.filter(
        project_id=OuterRef("project_id"), standard_id=OuterRef("standard_id")
    )
    return StandardExecution.objects.filter(Exists(attached), project__tenant=tenant)


@dataclass(frozen=True)
class AttentionItem:
    """One current result that needs attention."""

    level: str  # WARNING or CRITICAL
    project_id: object
    project_name: str
    standard_id: object
    standard_name: str
    execution_id: object
    score: int
    status: str  # display label, e.g. "Failed"
    when: datetime


def attention_items(tenant) -> list[AttentionItem]:
    """Current results that need attention, critical first, then newest.

    A result needs attention when its score is below healthy, or when it
    failed or errored at all (a failed run that still scored well is a
    warning). Returns the full ranked list; screens decide how many to show.
    """
    # In-flight rows score 0 until the worker finishes them; they would show
    # as critical and hide the real latest result for that pair.
    executions = (
        attached_executions(tenant)
        .exclude(status=StandardExecution.Status.RUNNING)
        .select_related("project")
        .order_by("-created_at")[:_RECENT_EXECUTIONS]
    )

    seen = set()
    items = []
    for ex in executions:
        key = (ex.project_id, ex.standard_id)
        if key in seen:
            continue
        seen.add(key)

        level = level_from_score(ex.score)
        failed = ex.status in (StandardExecution.Status.FAILED, StandardExecution.Status.ERROR)
        if level == HEALTHY and not failed:
            continue
        if level == HEALTHY:
            level = WARNING

        items.append(
            AttentionItem(
                level=level,
                project_id=ex.project_id,
                project_name=ex.project.name,
                standard_id=ex.standard_id,
                standard_name=ex.standard_name,
                execution_id=ex.id,
                score=ex.score,
                status=ex.get_status_display(),
                when=ex.created_at,
            )
        )

    rank = {CRITICAL: 2, WARNING: 1}
    items.sort(key=lambda i: (rank.get(i.level, 0), i.when), reverse=True)
    return items
