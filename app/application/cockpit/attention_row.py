from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class AttentionRow:
    """One project that needs you: its score (None when never checked), its
    health, the standards that pull its grade down (failed where they only
    lower it: Major or Minor there), worst first, and its stacks."""

    project: object
    score: object  # CommitScore | None
    tone: ScoreTone
    below_par: tuple = ()
    stacks: tuple = ()

    @property
    def owner(self) -> str:
        return self.project.owner
