from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Expectation:
    """The standards a check expects a finished result of (standard ids)."""

    standard_ids: tuple

    @classmethod
    def of(cls, candidates) -> "Expectation":
        """The candidates that apply to the commit."""
        return cls(tuple(str(c.standard_id) for c in candidates if c.applies))

    def __bool__(self) -> bool:
        return bool(self.standard_ids)

    def __len__(self) -> int:
        return len(self.standard_ids)

    def missing(self, results) -> list[str]:
        """The expected standards with no finished result among ``results``:
        empty when the commit is complete."""
        finished = {str(r.standard_id) for r in results if r.finished}
        return [str(i) for i in self.standard_ids if str(i) not in finished]
