"""Showing AI usage: ``{{ n|tokens }}`` gives 950, 12.4k, 3.1M; ``short_model``
shortens a model's name for a gauge."""
import re

from django import template

register = template.Library()


@register.filter
def tokens(value):
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return "—"
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if n >= size:
            shown = f"{n / size:.1f}".rstrip("0").rstrip(".")
            return f"{shown}{suffix}"
    return str(n)


@register.filter
def percent(share):
    """A share (0.0–1.0+) as a whole percent, capped for bar widths at 100."""
    try:
        return min(round(float(share) * 100), 100)
    except (TypeError, ValueError):
        return 0


@register.filter
def short_model(name):
    """A model's name short enough for a gauge label: no vendor prefix or
    release date, versions with dots, words apart; GPT keeps its hyphen:
    claude-haiku-4-5-20251001 → haiku 4.5, gpt-5-mini → gpt-5 mini."""
    text = re.sub(r"^(?:[a-z]+/)?(?:claude-)?", "", str(name or ""))
    text = re.sub(r"-\d{8}$", "", text)
    text = re.sub(r"(\d)-(\d)(?=$|-)", r"\1.\2", text)
    if text.startswith("gpt-"):
        return "gpt-" + text[4:].replace("-", " ")
    return text.replace("-", " ")
