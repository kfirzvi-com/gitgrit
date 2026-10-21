from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ScoreToneStyle:
    """How a score tone looks: the one place a tone gets its colour. Pages
    (CSS custom properties and ``gg-tone-*`` classes, from
    ``{% score_tone_styles %}``), the diagrams (the same values as JSON) and
    the README badge (an external SVG, so hex) all read it."""

    tone: ScoreTone
    color: str

    # Michal's palette: A+/A mint, B yellow, C orange, D coral, F deep red.
    COLOR_BY_TONE = {
        ScoreTone.HEALTHY: "#00d390",
        ScoreTone.WARNING: "#facc15",
        ScoreTone.CAUTION: "#fb923c",
        ScoreTone.CRITICAL: "#ff627d",
        ScoreTone.SEVERE: "#ef4444",
        ScoreTone.UNKNOWN: "#64748b",
    }

    @property
    def label(self) -> str:
        return self.tone.label

    @classmethod
    def for_tone(cls, tone) -> "ScoreToneStyle":
        tone = ScoreTone(tone) if tone in set(ScoreTone) else ScoreTone.UNKNOWN
        return cls(tone, cls.COLOR_BY_TONE[tone])

    @classmethod
    def every_tone(cls) -> list["ScoreToneStyle"]:
        return [cls.for_tone(tone) for tone in ScoreTone]

    @classmethod
    def as_css(cls) -> str:
        """A custom property per tone and the classes that use it:
        ``gg-tone-text-<tone>`` (text), ``gg-tone-bg-<tone>`` (fills) and
        ``gg-tone-card-<tone>`` (a card's tone, for scores.css)."""
        rules = [":root { " + " ".join(f"--gg-tone-{s.tone}: {s.color};" for s in cls.every_tone()) + " }"]
        for s in cls.every_tone():
            rules.append(f".gg-tone-text-{s.tone} {{ color: var(--gg-tone-{s.tone}); }}")
            rules.append(f".gg-tone-bg-{s.tone} {{ background-color: var(--gg-tone-{s.tone}); }}")
            rules.append(f".gg-tone-card-{s.tone} {{ --gg-card-tone: var(--gg-tone-{s.tone}); }}")
        return "\n".join(rules)

    @classmethod
    def as_json(cls) -> dict:
        """For the diagrams: ``{tone: {"color", "label"}}``."""
        return {str(s.tone): {"color": s.color, "label": s.label} for s in cls.every_tone()}
