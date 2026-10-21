from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepresentedScore:
    """How a score is shown: ``text`` (what the reader sees, e.g. "82" or
    "—"), ``tone`` (its colour band, one of ``app.domain.health``'s levels:
    healthy, warning, critical, unknown) and ``spoken`` (the same for screen
    readers and tooltips, e.g. "Score 82 out of 100")."""

    text: str
    tone: str
    spoken: str

    def as_dict(self) -> dict:
        """For the API: ``{"text", "tone", "spoken"}``."""
        return {"text": self.text, "tone": self.tone, "spoken": self.spoken}
