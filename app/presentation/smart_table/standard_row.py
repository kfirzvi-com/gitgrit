from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ProjectStandard, StandardExecution
from app.presentation.filter_search.standard_list_filter_search import StandardListFilterSearch

# Between several values in one data-filter-/data-group- attribute.
SEPARATOR = "|"

Status = StandardExecution.Status
FAILING = (Status.FAILED, Status.ERROR)


@dataclass
class StandardRow:
    """A standard as the Standards table shows it: how many projects it is
    attached to and, of those, how many its newest result on their default
    branch passes or fails (an error fails), and how many it has no result
    on yet."""

    standard: object
    projects: int = 0
    passing: int = 0
    failing: int = 0

    @classmethod
    def for_standards(cls, standards) -> list["StandardRow"]:
        """A row per standard; the attachments and newest results of them all
        read in two queries."""
        standards = list(standards)
        attached = {}
        for standard_id, project_id, branch in (
            ProjectStandard.objects.filter(standard__in=standards)
            .values_list("standard_id", "project_id", "project__default_branch")
        ):
            attached.setdefault(standard_id, {})[project_id] = branch
        newest = (
            StandardExecution.objects.filter(standard__in=standards)
            .exclude(status=Status.RUNNING)
            .order_by("standard_id", "project_id", "ref", "-created_at")
            .distinct("standard_id", "project_id", "ref")
            .values_list("standard_id", "project_id", "ref", "status")
        )
        outcomes = {}
        for standard_id, project_id, ref, status in newest:
            if attached.get(standard_id, {}).get(project_id) == ref:
                outcomes.setdefault(standard_id, []).append(status)
        rows = []
        for s in standards:
            statuses = outcomes.get(s.pk, [])
            rows.append(cls(
                standard=s,
                projects=len(attached.get(s.pk, {})),
                passing=sum(1 for st in statuses if st == Status.PASSED),
                failing=sum(1 for st in statuses if st in FAILING),
            ))
        return rows

    @property
    def unchecked(self) -> int:
        """Attached projects it has no passing or failing result on yet."""
        return max(self.projects - self.passing - self.failing, 0)

    @property
    def tone(self) -> str:
        """The row's edge: failing somewhere, passing everywhere it ran, or
        nothing to say."""
        if self.failing:
            return "failed"
        if self.passing:
            return "healthy"
        return "unknown"

    @property
    def pass_rate(self) -> str:
        """Passing share of the projects it has a result on (0 to 100), empty
        with none: what "Pass rate" sorts by."""
        checked = self.passing + self.failing
        return str(round(100 * self.passing / checked)) if checked else ""

    @property
    def status_value(self) -> str:
        """Its one status for grouping: draft, else enabled or disabled."""
        if self.standard.draft:
            return StandardListFilterSearch.DRAFT
        return StandardListFilterSearch.ENABLED if self.standard.enabled else StandardListFilterSearch.DISABLED

    @property
    def sort_status(self) -> int:
        return {"enabled": 0, "draft": 1, "disabled": 2}[self.status_value]

    @property
    def label_names(self) -> str:
        return SEPARATOR.join(self._clean(label.name) for label in self.standard.labels.all())

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(str(e) for e in (self.standard.criteria or {}).get("events", []) or ())

    @property
    def event_values(self) -> str:
        return SEPARATOR.join(self._clean(e).lower() for e in self.events)

    @property
    def source_value(self) -> str:
        return StandardListFilterSearch.source_of(self.standard)

    @staticmethod
    def _clean(text: str) -> str:
        return (text or "").replace(SEPARATOR, "/").strip()
