from __future__ import annotations

from app.domain.importance import Importance
from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.standard_filter_fields import StandardFilterFields


class StandardPickerFilterSearch:
    """The filters of a project's standards picker: whether a standard is
    attached, its importance on the project (attached standards only), its
    labels, name and description."""

    ATTACHED = "attached"
    DETACHED = "detached"

    @classmethod
    def for_standards(cls, standards) -> FilterSearch:
        shared = StandardFilterFields(standards)
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
                shared.label(),
                shared.name(),
                shared.description(),
            ),
            placeholder="Filter standards: is:attached importance:required label:ci",
        )
