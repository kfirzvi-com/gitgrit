from __future__ import annotations

from collections import Counter
from datetime import datetime

from app.domain.importance import Importance
from app.models import Project


class StandardsSummary:
    """The Overview's Standards card: how many standards are attached and
    active, how they split by importance, what runs them (changes, a
    schedule, or only a schedule) and when the next scheduled run is, and
    where they came from (the marketplace or written in the workspace).
    Read in one query."""

    def __init__(self, project: Project):
        self.attachments = list(project.project_standards.select_related("standard").order_by("standard__name"))

    @property
    def attached(self) -> int:
        return len(self.attachments)

    @property
    def active(self) -> int:
        return sum(1 for a in self.attachments if a.standard.enabled and not a.standard.draft)

    @property
    def inactive(self) -> int:
        return self.attached - self.active

    @property
    def by_importance(self) -> list[tuple[Importance, int]]:
        """Each importance, most important first, with how many standards
        have it (all three, zeros too, so the row reads the same everywhere)."""
        counts = Counter(a.importance for a in self.attachments)
        return [(importance, counts.get(importance.value, 0)) for importance in Importance]

    @property
    def on_changes(self) -> int:
        return sum(1 for a in self.attachments if a.runs_on_changes)

    @property
    def scheduled(self) -> int:
        return sum(1 for a in self.attachments if a.schedule)

    @property
    def schedule_only(self) -> int:
        return sum(1 for a in self.attachments if a.runs_only_on_schedule)

    @property
    def next_scheduled_run(self) -> datetime | None:
        due = [a.next_scheduled_run_at for a in self.attachments if a.schedule and a.next_scheduled_run_at]
        return min(due, default=None)

    @property
    def from_marketplace(self) -> int:
        return sum(1 for a in self.attachments if a.standard.source_marketplace_standard_id)

    @property
    def written_here(self) -> int:
        return self.attached - self.from_marketplace
