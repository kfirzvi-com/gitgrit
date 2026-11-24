from __future__ import annotations

from dataclasses import dataclass

from app.presentation.smart_table.column_option import ColumnOption
from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.sort_option import SortOption


@dataclass(frozen=True)
class SmartTable:
    """The sorts and groupings one list offers, in menu order, and how it
    reads first: sorted by ``default_sort`` (in its own direction), grouped
    by ``default_group`` (``""``: not grouped). ``noun`` counts the rows
    ("3 of 12 projects"). ``columns`` are the ones a viewer may hide."""

    sorts: tuple[SortOption, ...]
    groups: tuple[GroupOption, ...]
    default_sort: str
    noun: str
    noun_plural: str
    default_group: str = ""
    columns: tuple[ColumnOption, ...] = ()

    @property
    def hidden_columns(self) -> str:
        """The columns hidden until the viewer chooses, space-separated (the
        table's ``data-smart-hidden``)."""
        return " ".join(column.key for column in self.columns if not column.shown)

    def as_dict(self) -> dict:
        return {
            "sorts": [s.as_dict() for s in self.sorts],
            "groups": [g.as_dict() for g in self.groups],
            "defaultSort": self.default_sort,
            "defaultGroup": self.default_group,
            "noun": self.noun,
            "nounPlural": self.noun_plural,
            "columns": [c.as_dict() for c in self.columns],
        }
