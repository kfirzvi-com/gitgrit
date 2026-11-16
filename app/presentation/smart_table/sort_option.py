from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SortOption:
    """One order a smart table's rows can take: by ``data-sort-<key>``,
    compared as numbers when ``numeric``, else as text. ``descending`` is
    the direction a first pick sorts in (scores and counts read best or
    biggest first). A row with no value sorts last either way."""

    key: str
    label: str
    numeric: bool = False
    descending: bool = False

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "numeric": self.numeric, "descending": self.descending}
