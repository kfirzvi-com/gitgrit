from __future__ import annotations

from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_value import FilterValue


class StandardFilterFields:
    """The fields every list of standards offers: ``label:``, ``name:`` and
    ``description:``. Expects standards with their labels prefetched."""

    def __init__(self, standards):
        self.standards = list(standards)

    def label(self) -> FilterField:
        names = sorted({label.name for s in self.standards for label in s.labels.all()}, key=str.lower)
        return FilterField(
            key="label",
            label="Label",
            values=tuple(FilterValue(name.lower(), name) for name in names),
            has_menu=True,
            searched_by_words=True,
        )

    def name(self) -> FilterField:
        names = sorted({s.name for s in self.standards}, key=str.lower)
        return FilterField(
            key="name",
            label="Name",
            values=tuple(FilterValue(name.lower(), name) for name in names),
            matches_part=True,
            searched_by_words=True,
        )

    def description(self) -> FilterField:
        return FilterField(
            key="description",
            label="Description",
            matches_part=True,
            searched_by_words=True,
            hint="words in the description",
        )
