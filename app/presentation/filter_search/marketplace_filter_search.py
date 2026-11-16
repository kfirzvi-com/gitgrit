from __future__ import annotations

from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue


class MarketplaceFilterSearch:
    """The filters of the Marketplace: whether the workspace has a standard
    (``is:installed``, ``is:update`` for a newer version out, ``is:available``
    for not yet), its packs, labels, author and events, its name and
    description."""

    STATUSES = (
        FilterValue("available", "Not installed"),
        FilterValue("update", "Update available"),
        FilterValue("installed", "Installed"),
    )

    @classmethod
    def for_rows(cls, rows) -> FilterSearch:
        rows = list(rows)
        return FilterSearch(
            fields=(
                FilterField(key="is", label="Installed", values=cls.STATUSES, has_menu=True),
                FilterField(
                    key="pack", label="Pack",
                    values=cls._names({p.name for r in rows for p in r.packs}),
                    has_menu=True, searched_by_words=True,
                ),
                FilterField(
                    key="label", label="Label",
                    values=cls._names({str(lbl) for r in rows for lbl in r.standard.suggested_labels or ()}),
                    has_menu=True, searched_by_words=True,
                ),
                FilterField(
                    key="author", label="Author",
                    values=cls._names({r.author for r in rows if r.author}),
                    has_menu=True,
                ),
                FilterField(
                    key="event", label="Event",
                    values=cls._names({e for r in rows for e in r.events}),
                    has_menu=True,
                ),
                FilterField(
                    key="name", label="Name",
                    values=cls._names({r.standard.name for r in rows}),
                    matches_part=True, searched_by_words=True,
                ),
                FilterField(
                    key="description", label="Description",
                    matches_part=True, searched_by_words=True, hint="words in the description",
                ),
            ),
            placeholder="Filter the Marketplace: is:available pack:security label:ci",
        )

    @staticmethod
    def _names(names) -> tuple[FilterValue, ...]:
        return tuple(FilterValue(n.lower(), n) for n in sorted(names, key=str.lower))
