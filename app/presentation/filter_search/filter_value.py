from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterValue:
    """One value a filter field can take: ``value`` is what the query says
    (lower case, as rows say it), ``label`` how menus and suggestions show it."""

    value: str
    label: str

    def as_dict(self) -> dict:
        return {"value": self.value, "label": self.label}
