from __future__ import annotations

from dataclasses import dataclass

from app.presentation.filter_search.filter_field import FilterField


@dataclass(frozen=True)
class FilterSearch:
    """The fields one list can be filtered by, in the order autocomplete
    lists them, and the search box's placeholder."""

    fields: tuple[FilterField, ...]
    placeholder: str

    @property
    def menu_fields(self) -> tuple[FilterField, ...]:
        """The fields with a menu button, in order."""
        return tuple(f for f in self.fields if f.has_menu)

    def as_dict(self) -> dict:
        return {"fields": [f.as_dict() for f in self.fields], "placeholder": self.placeholder}
