"""Scores in templates, all through ``SCORE_REPRESENTATION``.

    {% load score_tags %}
    {% score project_score.value failed=project_score.failed size="xl" %}
    {{ value|score_text }}

``score`` renders ``partials/score.html``: the text in its tone's colour,
with the spoken form for screen readers and tooltips. ``score_text`` is the
bare text, for places that are not HTML (titles, attributes).
"""
from django import template

from app.domain.score_representation import SCORE_REPRESENTATION

register = template.Library()


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
