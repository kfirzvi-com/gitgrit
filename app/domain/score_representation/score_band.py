from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreBand:
    """One step of the score scale: a letter and the scores it covers,
    ``lowest`` to ``highest`` (both included)."""

    letter: str
    lowest: int
    highest: int

    @property
    def range_text(self) -> str:
        """The scores it covers as numbers show them: "100", "90–99"."""
        return str(self.lowest) if self.lowest == self.highest else f"{self.lowest}–{self.highest}"

    def covers(self, value) -> bool:
        return self.lowest <= value <= self.highest
