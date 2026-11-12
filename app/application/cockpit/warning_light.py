from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class WarningLight:
    """One lamp on the dashboard, for one kind of trouble: how many projects
    are in it, and the tone it lights in when there are any."""

    key: str
    title: str
    count: int
    tone: ScoreTone

    @property
    def lit(self) -> bool:
        return self.count > 0
