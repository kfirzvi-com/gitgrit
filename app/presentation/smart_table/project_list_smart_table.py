from __future__ import annotations

from app.domain.models import Platform, Project
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.project_row import HEALTH_ORDER, ProjectRow
from app.presentation.smart_table.smart_table import SmartTable
from app.presentation.smart_table.sort_option import SortOption


class ProjectListSmartTable:
    """The Projects page's table: sorted by name, score, health (worst
    first), owner, lifecycle, stacks or when last checked; grouped by owner,
    stack, health, lifecycle or platform."""

    @classmethod
    def build(cls) -> SmartTable:
        return SmartTable(
            sorts=(
                SortOption("name", "Name"),
                SortOption("score", "Score", numeric=True, descending=True),
                SortOption("health", "Health (worst first)", numeric=True),
                SortOption("owner", "Owner"),
                SortOption("lifecycle", "Lifecycle", numeric=True),
                SortOption("stacks", "Stacks", numeric=True, descending=True),
                SortOption("checked", "Last checked", numeric=True, descending=True),
            ),
            groups=(
                GroupOption("owner", "Owner", empty_label="No owner"),
                GroupOption("stack", "Stack", empty_label="In no stack"),
                GroupOption(
                    "health", "Health", empty_label="",
                    values=tuple(FilterValue(ProjectRow.health_slug(t), t.label) for t in HEALTH_ORDER),
                ),
                GroupOption(
                    "lifecycle", "Lifecycle", empty_label="",
                    values=tuple(FilterValue(v, label) for v, label in Project.Lifecycle.choices),
                ),
                GroupOption(
                    "platform", "Platform", empty_label="",
                    values=tuple(FilterValue(v, label) for v, label in Platform.choices),
                ),
            ),
            default_sort="name",
            noun="project",
            noun_plural="projects",
        )
