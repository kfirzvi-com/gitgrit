"""Scores in templates. A commit's score (and a branch's or a project's)
goes through ``COMMIT_SCORE_REPRESENTATION``; one standard's result through
``STANDARD_RESULT_REPRESENTATION``.

    {% load score_tags %}
    {% score project_score.value failed=project_score.failed size="xl" %}
    {% standard_result_score ex.score size="sm" %}
    {{ value|score_text }}

``score`` and ``standard_result_score`` render ``partials/score.html``: the
text in its tone's colour, with the spoken form for screen readers and
tooltips. ``score_text`` is a commit score's bare text, for places that are
not HTML (titles, attributes).
"""
from django import template
from django.utils.html import json_script
from django.utils.safestring import mark_safe

from app.domain.score_representation import COMMIT_SCORE_REPRESENTATION, STANDARD_RESULT_REPRESENTATION
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


def _score_context(representation, value, failed, size, toned, data_attr):
    return {
        "represented": representation.represent(_value(value), failed=bool(failed)),
        "size": size,
        "toned": toned,
        "data_attr": data_attr,
    }


@register.inclusion_tag("partials/score.html")
def score(value, failed=False, size="md", toned=True, data_attr=""):
    """A commit's score (or a branch's or a project's), as
    ``COMMIT_SCORE_REPRESENTATION`` shows it. ``size``: sm, md, card, lg, xl,
    hero."""
    return _score_context(COMMIT_SCORE_REPRESENTATION, value, failed, size, toned, data_attr)


@register.inclusion_tag("partials/score.html")
def standard_result_score(value, failed=False, size="md", toned=True, data_attr=""):
    """One standard's result on a commit, as ``STANDARD_RESULT_REPRESENTATION``
    shows it. ``failed``: a Required standard's failure, which fails the commit.
    ``toned=False`` leaves it in the text colour (beside its status dot)."""
    return _score_context(STANDARD_RESULT_REPRESENTATION, value, failed, size, toned, data_attr)


@register.simple_tag
def score_tone(value, failed=False):
    """The colour a commit score is painted in (its ``shade``: its health's,
    or orange for a D), e.g. for a card's class:
    ``{% score_tone value failed as tone %}``."""
    return COMMIT_SCORE_REPRESENTATION.represent(_value(value), failed=bool(failed)).shade


@register.simple_tag
def score_scale():
    """Every value ``COMMIT_SCORE_REPRESENTATION`` can show, best first, as
    ``[{"text", "tone"}]`` (A+ to F for letters; empty for numbers)."""
    return [{"text": step.text, "tone": step.shade} for step in COMMIT_SCORE_REPRESENTATION.scale()]


@register.simple_tag
def score_text_of(value, failed=False):
    """A score's text with its failed flag: ``{% score_text_of v f as text %}``."""
    return COMMIT_SCORE_REPRESENTATION.represent(_value(value), failed=bool(failed)).text


@register.filter
def score_text(value):
    """The score's text alone ("82", "—")."""
    return COMMIT_SCORE_REPRESENTATION.represent(_value(value)).text
