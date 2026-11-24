from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnOption:
    """A smart table column a viewer may show or hide: its header and cells
    carry ``data-smart-column="<key>"``. ``shown`` is how it starts before
    the viewer chooses."""

    key: str
    label: str
    shown: bool = True

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "shown": self.shown}
