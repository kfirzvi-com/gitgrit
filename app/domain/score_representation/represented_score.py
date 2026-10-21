from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation.score_tone import ScoreTone


@dataclass(frozen=True)
class RepresentedScore:
    """How a score is shown: ``text`` (what the reader sees, e.g. "82" or
    "—"), ``tone`` (its colour band, a ``ScoreTone``) and ``spoken`` (the
    same for screen readers and tooltips, e.g. "Score 82 out of 100")."""

    text: str
    tone: ScoreTone
    spoken: str

    def as_dict(self) -> dict:
        """For the API: ``{"text", "tone", "spoken"}``."""
        return {"text": self.text, "tone": str(self.tone), "spoken": self.spoken}
