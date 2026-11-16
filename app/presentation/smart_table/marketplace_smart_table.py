from __future__ import annotations

from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.marketplace_filter_search import MarketplaceFilterSearch
from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.smart_table import SmartTable
from app.presentation.smart_table.sort_option import SortOption


class MarketplaceSmartTable:
    """The Marketplace's table of standards: sorted by name, whether the
    workspace has it, author, version or when last published; grouped by
    pack, label, author or whether it is installed (a standard in two packs
    shows under both)."""

    @classmethod
    def build(cls) -> SmartTable:
        return SmartTable(
            sorts=(
                SortOption("name", "Name"),
                SortOption("status", "Installed (not yet first)", numeric=True),
                SortOption("author", "Author"),
                SortOption("version", "Version", numeric=True, descending=True),
                SortOption("updated", "Last published", numeric=True, descending=True),
            ),
            groups=(
                GroupOption("pack", "Pack", empty_label="In no pack"),
                GroupOption("label", "Label", empty_label="No label"),
                GroupOption("author", "Author", empty_label="No author"),
                GroupOption(
                    "status", "Installed", empty_label="",
                    values=tuple(FilterValue(v.value, v.label) for v in MarketplaceFilterSearch.STATUSES),
                ),
            ),
            default_sort="name",
            noun="standard",
            noun_plural="standards",
        )
