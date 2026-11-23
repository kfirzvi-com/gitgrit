from __future__ import annotations

from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.smart_table import SmartTable
from app.presentation.smart_table.sort_option import SortOption


class StackListSmartTable:
    """The Stacks page's table: sorted by name, its projects counted by
    health, how many projects it has; grouped by the owners of
    its projects (a stack with projects of two owners shows under both)."""

    @classmethod
    def build(cls) -> SmartTable:
        return SmartTable(
            sorts=(
                SortOption("name", "Name"),
                SortOption("failed", "Failed projects", numeric=True, descending=True),
                SortOption("attention", "Projects needing attention", numeric=True, descending=True),
                SortOption("healthy", "Healthy projects", numeric=True, descending=True),
                SortOption("share", "Share healthy", numeric=True, descending=True),
                SortOption("projects", "Projects", numeric=True, descending=True),
            ),
            groups=(
                GroupOption("owner", "Owner", empty_label="No owner"),
            ),
            default_sort="name",
            noun="stack",
            noun_plural="stacks",
        )
