"""Scores in templates, all through ``SCORE_REPRESENTATION``.

    {% load score_tags %}
    {% score project_score.value failed=project_score.failed size="xl" %}
    {{ value|score_text }}

``score`` renders ``partials/score.html``: the text in its tone's colour,
with the spoken form for screen readers and tooltips. ``score_text`` is the
bare text, for places that are not HTML (titles, attributes).
"""
from django import template
from django.utils.html import json_script
from django.utils.safestring import mark_safe

from app.domain.score_representation import SCORE_REPRESENTATION
from app.presentation.score_tones import ScoreToneStyle

register = template.Library()


def _value(value):
    """A template's missing value (``""`` for a missing attribute, e.g. a
    project with no score yet) is no score."""
    return None if value in ("", None) else value


@register.simple_tag
def score_tone_styles():
    """The tones' colours for the whole page, from ``ScoreToneStyle``: CSS
    custom properties and ``gg-tone-*`` classes, and the same values as JSON
    (``#gg-score-tones``) for the diagrams. Once, in base.html."""
    return mark_safe(
        f"<style>\n{ScoreToneStyle.as_css()}\n</style>\n"
        + json_script(ScoreToneStyle.as_json(), "gg-score-tones")
    )


@register.inclusion_tag("partials/score.html")
def score(value, failed=False, size="md", toned=True, data_attr=""):
    """One score, shown the one way GitGrit shows scores. ``size``: sm, md, card,
    lg, xl. ``toned=False`` leaves it in the text colour (a standard's score
    beside its status dot)."""
    return {
        "represented": SCORE_REPRESENTATION.represent(_value(value), failed=bool(failed)),
        "size": size,
        "toned": toned,
        "data_attr": data_attr,
    }


@register.simple_tag
def score_tone(value, failed=False):
    """A score's tone (``SCORE_REPRESENTATION``), e.g. for a card's class:
    ``{% score_tone value failed as tone %}``."""
    return str(SCORE_REPRESENTATION.represent(_value(value), failed=bool(failed)).tone)


@register.simple_tag
def score_scale():
    """Every value ``SCORE_REPRESENTATION`` can show, best first, as
    ``[{"text", "tone"}]`` (A+ to F for letters; empty for numbers)."""
    return [{"text": text, "tone": str(tone)} for text, tone in SCORE_REPRESENTATION.scale()]


@register.simple_tag
def score_text_of(value, failed=False):
    """A score's text with its failed flag: ``{% score_text_of v f as text %}``."""
    return SCORE_REPRESENTATION.represent(_value(value), failed=bool(failed)).text


@register.filter
def score_text(value):
    """The score's text alone ("82", "—")."""
    return SCORE_REPRESENTATION.represent(_value(value)).text
