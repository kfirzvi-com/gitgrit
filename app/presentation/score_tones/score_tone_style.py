from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone


@dataclass(frozen=True)
class ScoreToneStyle:
    """How a score tone looks: the one place a tone gets its colour. Pages
    (CSS custom properties and ``gg-tone-*`` classes, from
    ``{% score_tone_styles %}``), the diagrams (the same values as JSON) and
    the README badge (an external SVG, so hex) all read it."""

    tone: str  # a ScoreTone, or a shade a representation paints apart ("low")
    color: str
    label: str

    # From Michal's palette: healthy (A+, A) mint, needs attention (B, C)
    # yellow, failed (F) red, no data gray. Red means failed, nothing else.
    COLOR_BY_TONE = {
        ScoreTone.HEALTHY: "#00d390",
        ScoreTone.NEEDS_ATTENTION: "#facc15",
        ScoreTone.FAILED: "#ef4444",
        ScoreTone.UNKNOWN: "#64748b",
    }
    # Shades that paint a tone apart, with the tone they still mean: a D is
    # orange (``ScoreBands.LOW_SHADE``, the lowest band), and needs attention.
    SHADES = {"low": ("#fb923c", ScoreTone.NEEDS_ATTENTION)}

    @classmethod
    def for_tone(cls, tone) -> "ScoreToneStyle":
        """The style of a tone or a shade; unknown for anything else."""
        if tone in cls.SHADES:
            color, meaning = cls.SHADES[tone]
            return cls(str(tone), color, meaning.label)
        tone = ScoreTone(tone) if tone in set(ScoreTone) else ScoreTone.UNKNOWN
        return cls(str(tone), cls.COLOR_BY_TONE[tone], tone.label)

    @classmethod
    def every_tone(cls) -> list["ScoreToneStyle"]:
        """Every tone, then every shade."""
        return [cls.for_tone(tone) for tone in ScoreTone] + [cls.for_tone(shade) for shade in cls.SHADES]

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
