from __future__ import annotations

from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.standard_list_filter_search import StandardListFilterSearch
from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.smart_table import SmartTable
from app.presentation.smart_table.sort_option import SortOption


class StandardListSmartTable:
    """The Standards page's table: sorted by name, status, how many projects
    it is attached to, how many it fails, its pass rate or when last changed;
    grouped by label, status, event or source (a standard with two labels
    shows under both)."""

    @classmethod
    def build(cls) -> SmartTable:
        return SmartTable(
            sorts=(
                SortOption("name", "Name"),
                SortOption("status", "Status", numeric=True),
                SortOption("projects", "Projects attached", numeric=True, descending=True),
                SortOption("failing", "Failing projects", numeric=True, descending=True),
                SortOption("rate", "Pass rate", numeric=True),
                SortOption("updated", "Last changed", numeric=True, descending=True),
            ),
            groups=(
                GroupOption("label", "Label", empty_label="No label"),
                GroupOption(
                    "status", "Status", empty_label="",
                    values=(
                        FilterValue(StandardListFilterSearch.ENABLED, "Enabled"),
                        FilterValue(StandardListFilterSearch.DRAFT, "Draft"),
                        FilterValue(StandardListFilterSearch.DISABLED, "Disabled"),
                    ),
                ),
                GroupOption("event", "Event", empty_label="No events"),
                GroupOption("source", "Source", empty_label="", values=StandardListFilterSearch.SOURCES),
            ),
            default_sort="name",
            noun="standard",
            noun_plural="standards",
        )
