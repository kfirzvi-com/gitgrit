from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation.score_tone import ScoreTone


@dataclass(frozen=True)
class RepresentedScore:
    """How a score is shown: ``text`` (what the reader sees, e.g. "82" or
    "—"), ``tone`` (its health, a ``ScoreTone``), ``spoken`` (the same for
    screen readers and tooltips, e.g. "Score 82 out of 100") and ``shade``
    (the colour it is painted in: its tone's, unless the representation
    shades it apart, like a D in orange, still needing attention)."""

    text: str
    tone: ScoreTone
    spoken: str
    shade: str = ""

    def __post_init__(self):
        if not self.shade:
            object.__setattr__(self, "shade", str(self.tone))

    def as_dict(self) -> dict:
        """For the API: ``{"text", "tone", "spoken"}``."""
        return {"text": self.text, "tone": str(self.tone), "spoken": self.spoken}
