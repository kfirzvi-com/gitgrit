from __future__ import annotations

from django.utils import timezone

from app.domain import schedules
from app.domain.models import ProjectStandard


class AttachmentSchedules:
    """What runs a project's attached standards: on changes, on a schedule,
    or both. Schedules are read in ``time_zone`` (the person setting them)."""

    def __init__(self, project, time_zone: str = "UTC"):
        self.project = project
        self.time_zone = time_zone or "UTC"

    def parse(self, posted: dict) -> dict:
        """``posted`` (standard id -> (trigger, cron text[, time zone])) as
        standard id -> ``schedules.StandardSchedule``; a schedule without a
        time zone is read in this one's. Raises ``schedules.InvalidSchedule``,
        naming the standard, before anything is written."""
        parsed = {}
        for standard_id, (trigger, cron_text, *zone) in posted.items():
            time_zone = (zone[0] if zone else "") or self.time_zone
            try:
                parsed[str(standard_id)] = schedules.StandardSchedule.parse(trigger, cron_text, time_zone)
            except schedules.InvalidSchedule as exc:
                raise schedules.InvalidSchedule(f"{self._name(standard_id)}: {exc}") from None
        return parsed

    def _name(self, standard_id) -> str:
        attachment = (
            ProjectStandard.objects.filter(project=self.project, standard_id=standard_id)
            .select_related("standard")
            .first()
        )
        return attachment.standard.name if attachment else "A standard"

    def apply(self, by_standard: dict, now=None) -> int:
        """Set each attached standard's schedule from ``by_standard``
        (standard id -> ``StandardSchedule``); standards not attached are
        ignored, attached ones left out keep theirs. Returns how many
        changed."""
        now = now or timezone.now()
        changed = []
        for attachment in ProjectStandard.objects.filter(
            project=self.project, standard_id__in=list(by_standard)
        ):
            if attachment.apply_schedule(by_standard[str(attachment.standard_id)], now):
                changed.append(attachment)
        ProjectStandard.objects.bulk_update(
            changed, ["runs_on_changes", "schedule", "schedule_time_zone", "next_scheduled_run_at"]
        )
        return len(changed)
