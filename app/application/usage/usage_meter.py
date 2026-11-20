from __future__ import annotations

import logging
from datetime import date

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from app.domain.models import ExecutionUsage, Project, Tenant, WorkspaceUsageDay

logger = logging.getLogger(__name__)


class UsageMeter:
    """Counts a workspace's usage into one row per UTC day.

    Each count is an atomic increment, so concurrent runs never lose one.
    Metering never fails the work it meters: an error is logged and the
    work goes on (inside the caller's transaction, through a savepoint)."""

    @classmethod
    def record_executions(cls, project, count: int, trigger: str, *, on: date | None = None) -> None:
        """``count`` standard runs were queued on ``project`` by ``trigger``
        (the event type: push, pull_request, manual, upload). Also notes how
        many projects the workspace holds, so every active day has its peak."""
        if count <= 0:
            return

        def split(day):
            row, _ = ExecutionUsage.objects.get_or_create(
                tenant_id=project.tenant_id, day=day, project_id=project.pk, trigger=trigger or "manual",
                defaults={"project_name": project.name},
            )
            ExecutionUsage.objects.filter(pk=row.pk).update(
                executions=F("executions") + count, project_name=project.name
            )

        cls._safely(project.tenant_id, on, also=split, executions=F("executions") + count)

    @classmethod
    def record_projects(cls, tenant_id, *, on: date | None = None) -> None:
        """The workspace's project count may have grown: raise the day's peak."""
        cls._safely(tenant_id, on)

    @classmethod
    def snapshot_all(cls, *, on: date | None = None) -> int:
        """Note every workspace's project count for the day, so a month with
        no runs and no new projects still shows the projects held. Returns
        how many workspaces were noted."""
        tenant_ids = list(Tenant.objects.values_list("pk", flat=True))
        for tenant_id in tenant_ids:
            cls.record_projects(tenant_id, on=on)
        return len(tenant_ids)

    @classmethod
    def _safely(cls, tenant_id, on: date | None, also=None, **updates) -> None:
        day = on or timezone.now().date()
        try:
            with transaction.atomic():
                projects = Project.objects.filter(tenant_id=tenant_id).count()
                row, _ = WorkspaceUsageDay.objects.get_or_create(tenant_id=tenant_id, day=day)
                WorkspaceUsageDay.objects.filter(pk=row.pk).update(
                    peak_projects=Greatest(F("peak_projects"), projects), **updates
                )
                if also:
                    also(day)
        except Exception:  # noqa: BLE001 — never lose the work over metering
            logger.exception("Could not meter usage for workspace %s on %s", tenant_id, day)
