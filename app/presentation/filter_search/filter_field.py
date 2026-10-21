from __future__ import annotations

from dataclasses import dataclass, field

from app.presentation.filter_search.filter_value import FilterValue


@dataclass(frozen=True)
class FilterField:
    """One field a filter query can name (``key:value``).

    ``values`` are what autocomplete offers. A field with ``has_menu`` also
    gets a menu button that ticks values; ``matches_part`` fields (a name, a
    description) match any row whose value contains the query's, the others
    need the exact value. ``searched_by_words`` fields are what free words
    look in."""

    key: str
    label: str
    values: tuple[FilterValue, ...] = field(default_factory=tuple)
    has_menu: bool = False
    matches_part: bool = False
    searched_by_words: bool = False
    hint: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "values": [v.as_dict() for v in self.values],
            "hasMenu": self.has_menu,
            "matchesPart": self.matches_part,
            "searchedByWords": self.searched_by_words,
            "hint": self.hint,
        }
