from __future__ import annotations

from app.domain.importance import Importance
from app.domain.schedules import RunTrigger
from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.standard_filter_fields import StandardFilterFields


class StandardPickerFilterSearch:
    """The filters of a project's standards picker: whether a standard is
    attached, its importance on the project (attached standards only), its
    labels, name and description; on a project, what runs it (every
    change, a schedule, or both)."""

    ATTACHED = "attached"
    DETACHED = "detached"

    @classmethod
    def for_standards(cls, standards, with_runs: bool = False) -> FilterSearch:
        shared = StandardFilterFields(standards)
        runs = (
            FilterField(
                key="runs",
                label="Runs",
                values=tuple(FilterValue(t.value, t.label) for t in RunTrigger),
                has_menu=True,
            ),
        ) if with_runs else ()
        return FilterSearch(
            fields=(
                FilterField(
                    key="is",
                    label="Attached",
                    values=(FilterValue(cls.ATTACHED, "Attached"), FilterValue(cls.DETACHED, "Not attached")),
                    has_menu=True,
                ),
                FilterField(
                    key="importance",
                    label="Importance",
                    values=tuple(FilterValue(i.value, i.label) for i in Importance),
                    has_menu=True,
                    hint="of the attached standards",
                ),
                *runs,
                shared.label(),
                shared.name(),
                shared.description(),
            ),
            placeholder="Filter standards: is:attached importance:required label:ci",
        )
