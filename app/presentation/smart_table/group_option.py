from __future__ import annotations

from dataclasses import dataclass, field

from app.presentation.filter_search.filter_value import FilterValue


@dataclass(frozen=True)
class GroupOption:
    """One way to group a smart table's rows: by ``data-group-<key>``.

    ``values`` fixes the groups' order and labels when they are known up
    front (health: failed first); otherwise the groups are the rows' own
    values, A to Z. Rows with none go in a last group, ``empty_label``."""

    key: str
    label: str
    empty_label: str
    values: tuple[FilterValue, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "emptyLabel": self.empty_label,
            "values": [v.as_dict() for v in self.values],
        }
