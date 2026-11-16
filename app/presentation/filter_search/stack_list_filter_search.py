from __future__ import annotations

from app.domain.score_representation import ScoreTone
from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue


class StackListFilterSearch:
    """The filters of the workspace's Stacks page: the health its projects
    have (``has:failed``: a stack with at least one failed project), the
    owners of its projects, its projects, its name and description."""

    @classmethod
    def for_rows(cls, rows) -> FilterSearch:
        rows = list(rows)
        return FilterSearch(
            fields=(
                FilterField(
                    key="has",
                    label="Has projects",
                    values=tuple(
                        FilterValue(t.value.replace("_", "-"), t.label)
                        for t in (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)
                    ),
                    has_menu=True,
                    hint="stacks with a project of this health",
                ),
                FilterField(
                    key="owner",
                    label="Owner",
                    values=cls._names({o for r in rows for o in r.owners}),
                    has_menu=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="project",
                    label="Project",
                    values=cls._names({p.name for r in rows for p in r.projects}),
                    has_menu=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="name",
                    label="Name",
                    values=cls._names({r.stack.name for r in rows}),
                    matches_part=True,
                    searched_by_words=True,
                ),
                FilterField(
                    key="description",
                    label="Description",
                    matches_part=True,
                    searched_by_words=True,
                    hint="words in the description",
                ),
            ),
            placeholder="Filter stacks: has:failed owner:\"platform team\"",
        )

    @staticmethod
    def _names(names) -> tuple[FilterValue, ...]:
        return tuple(FilterValue(n.lower(), n) for n in sorted(names, key=str.lower))
