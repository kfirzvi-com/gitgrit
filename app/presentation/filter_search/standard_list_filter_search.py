from __future__ import annotations

from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.standard_filter_fields import StandardFilterFields


class StandardListFilterSearch:
    """The filters of the workspace's Standards page: whether a standard runs
    (enabled, disabled, draft), its labels, the events it runs on, where it
    came from (the Marketplace or written here), its name and description."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    DRAFT = "draft"
    SOURCES = (FilterValue("marketplace", "Marketplace"), FilterValue("custom", "Custom"))

    @classmethod
    def for_standards(cls, standards) -> FilterSearch:
        standards = list(standards)
        shared = StandardFilterFields(standards)
        return FilterSearch(
            fields=(
                FilterField(
                    key="is",
                    label="Status",
                    values=(
                        FilterValue(cls.ENABLED, "Enabled"),
                        FilterValue(cls.DISABLED, "Disabled"),
                        FilterValue(cls.DRAFT, "Draft"),
                    ),
                    has_menu=True,
                ),
                shared.label(),
                FilterField(
                    key="event",
                    label="Event",
                    values=tuple(
                        FilterValue(e.lower(), e)
                        for e in sorted({str(e) for s in standards for e in (s.criteria or {}).get("events", []) or ()})
                    ),
                    has_menu=True,
                ),
                FilterField(key="source", label="Source", values=cls.SOURCES, has_menu=True),
                shared.name(),
                shared.description(),
            ),
            placeholder="Filter standards: is:enabled label:security",
        )

    @classmethod
    def statuses_of(cls, standard) -> list[str]:
        """What ``is:`` matches for ``standard``: enabled or disabled, and
        draft too when it is one."""
        statuses = [cls.ENABLED if standard.enabled else cls.DISABLED]
        if standard.draft:
            statuses.append(cls.DRAFT)
        return statuses

    @staticmethod
    def source_of(standard) -> str:
        """What ``source:`` matches: ``marketplace`` for a standard added from
        the Marketplace, else ``custom``."""
        return "marketplace" if standard.source_marketplace_standard_id else "custom"
