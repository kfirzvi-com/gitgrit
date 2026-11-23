from __future__ import annotations

import logging
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from app.domain.models import ProjectStandard

logger = logging.getLogger(__name__)


class StandardScheduler:
    """Runs the attached standards whose schedule is due
    (``app.domain.schedules``, rule 4). The worker calls ``run_due`` every
    minute; any number of workers may: each due attachment is taken by one
    (row locks, skipping the ones another holds)."""

    def run_due(self, now=None) -> int:
        """Queue every due standard's scheduled run, one check per project,
        and move each to its next time. Returns how many runs were queued."""
        from app.application.standard_runs import enqueue_scheduled_run

        now = now or timezone.now()
        with transaction.atomic():
            due = list(
                ProjectStandard.objects.select_for_update(skip_locked=True, of=("self",))
                .filter(next_scheduled_run_at__lte=now)
                .exclude(schedule="")
                .select_related("project", "standard")
            )
            # Missed times are not caught up one by one: next is after now.
            for attachment in due:
                attachment.advance_schedule(now)
            ProjectStandard.objects.bulk_update(due, ["next_scheduled_run_at"])

        by_project = defaultdict(list)
        projects = {}
        for attachment in due:
            standard = attachment.standard
            if standard.archived_at or not standard.enabled or standard.draft:
                continue
            projects[attachment.project_id] = attachment.project
            by_project[attachment.project_id].append(standard)

        queued = 0
        for project_id, standards in by_project.items():
            try:
                summary = enqueue_scheduled_run(projects[project_id], standards)
            except Exception:
                logger.exception("Scheduled run failed to queue for project %s", project_id)
                continue
            queued += summary["queued"] if summary else 0
        if queued:
            logger.info("Queued %d scheduled standard run(s)", queued)
        return queued
