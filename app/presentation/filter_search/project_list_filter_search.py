from __future__ import annotations

from app.domain.models import Platform, Project
from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.smart_table.project_row import HEALTH_ORDER, ProjectRow


class ProjectListFilterSearch:
    """The filters of the workspace's Projects page: a project's health, its
    stacks, owner, lifecycle, platform and languages, its name and path."""

    @classmethod
    def for_rows(cls, rows) -> FilterSearch:
        rows = list(rows)
        return FilterSearch(
            fields=(
                FilterField(
                    key="health",
                    label="Health",
                    values=tuple(FilterValue(ProjectRow.health_slug(t), t.label) for t in HEALTH_ORDER),
                    has_menu=True,
                ),
                FilterField(
                    key="stack",
                    label="Stack",
                    values=cls._names({s.name for r in rows for s in r.stacks}),
                    has_menu=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="owner",
                    label="Owner",
                    values=cls._names({r.owner_value for r in rows if r.owner_value}),
                    has_menu=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="lifecycle",
                    label="Lifecycle",
                    values=tuple(FilterValue(v, label) for v, label in Project.Lifecycle.choices),
                    has_menu=True,
                ),
                FilterField(
                    key="platform",
                    label="Platform",
                    values=tuple(FilterValue(v, label) for v, label in Platform.choices),
                    has_menu=True,
                ),
                FilterField(
                    key="language",
                    label="Language",
                    values=cls._names({str(lang) for r in rows for lang in r.project.languages or ()}),
                    has_menu=True,
                ),
                FilterField(
                    key="name",
                    label="Name",
                    values=cls._names({r.project.name for r in rows}),
                    matches_part=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="path",
                    label="Path",
                    matches_part=True,
                    searched_by_words=True,
                    hint="words in the repository path",
                ),
            ),
            placeholder="Filter projects: health:failed stack:orders lifecycle:production",
        )

    @staticmethod
    def _names(names) -> tuple[FilterValue, ...]:
        return tuple(FilterValue(n.lower(), n) for n in sorted(names, key=str.lower))
