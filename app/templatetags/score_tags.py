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
    """One score, shown the one way GitGrit shows scores. ``size``: sm, md,
    lg, xl. ``toned=False`` leaves it in the text colour (a standard's score
    beside its status dot)."""
    return {
        "represented": SCORE_REPRESENTATION.represent(value, failed=bool(failed)),
        "size": size,
        "toned": toned,
        "data_attr": data_attr,
    }


@register.filter
def score_text(value):
    """The score's text alone ("82", "—")."""
    return SCORE_REPRESENTATION.represent(value).text
