"""Scores in templates. A commit's score (and a branch's or a project's)
reads as the request's workspace prefers (``Tenant.score_representation``:
letters or numbers; ``COMMIT_SCORE_REPRESENTATION`` outside a workspace);
one standard's result through ``STANDARD_RESULT_REPRESENTATION``.

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
from app.presentation.older_commit_note import OlderCommitNote
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


def _commit_representation(context):
    """How the request's workspace reads commit scores; the default (letters)
    outside one (an email, a page without a workspace)."""
    tenant = getattr(context.get("request"), "tenant", None)
    return tenant.score_representation if tenant else COMMIT_SCORE_REPRESENTATION


def _score_context(representation, value, failed, size, toned, data_attr):
    return {
        "represented": representation.represent(_value(value), failed=bool(failed)),
        "size": size,
        "toned": toned,
        "data_attr": data_attr,
    }


@register.inclusion_tag("partials/score.html", takes_context=True)
def score(context, value, failed=False, size="md", toned=True, data_attr=""):
    """A commit's score (or a branch's or a project's), as the workspace reads
    it (letters or numbers). ``size``: sm, md, card, lg, xl, hero."""
    return _score_context(_commit_representation(context), value, failed, size, toned, data_attr)


@register.inclusion_tag("partials/score.html")
def standard_result_score(value, failed=False, size="md", toned=True, data_attr=""):
    """One standard's result on a commit, as ``STANDARD_RESULT_REPRESENTATION``
    shows it. ``failed``: a Required standard's failure, which fails the commit.
    ``toned=False`` leaves it in the text colour (beside its status dot)."""
    return _score_context(STANDARD_RESULT_REPRESENTATION, value, failed, size, toned, data_attr)


@register.simple_tag(takes_context=True)
def score_tone(context, value, failed=False):
    """The colour a commit score is painted in (its ``shade``: its health's,
    or orange for a D), e.g. for a card's class:
    ``{% score_tone value failed as tone %}``."""
    return _commit_representation(context).represent(_value(value), failed=bool(failed)).shade


@register.simple_tag(takes_context=True)
def score_scale(context):
    """Every value the workspace's representation can show, best first, as
    ``[{"text", "tone", "spoken"}]``: A+ to F for letters, the colour bands
    (90-100, 0-89, Failed) for numbers."""
    return [
        {"text": step.text, "tone": step.shade, "spoken": step.spoken}
        for step in _commit_representation(context).scale()
    ]


@register.simple_tag(takes_context=True)
def score_scale_name(context):
    """What the scale is called: "Grade" for letters, "Score" for numbers."""
    return _commit_representation(context).SCALE_NAME


@register.simple_tag(takes_context=True)
def score_scale_step_of(context, value, failed=False):
    """The scale step a score falls in (its letter, or its number's band)."""
    return _commit_representation(context).scale_step_of(_value(value), failed=bool(failed))


@register.simple_tag(takes_context=True)
def score_text_of(context, value, failed=False):
    """A score's text with its failed flag: ``{% score_text_of v f as text %}``."""
    return _commit_representation(context).represent(_value(value), failed=bool(failed)).text


@register.simple_tag
def older_commit_text(newest, shown=None):
    """``OlderCommitNote.text``: why a project shows an older commit."""
    return OlderCommitNote.text(newest, shown) if newest else ""


@register.filter
def score_text(value):
    """The score's text alone ("B", "—"), in the default representation (a
    filter sees no workspace): for old notifications' saved scores."""
    return COMMIT_SCORE_REPRESENTATION.represent(_value(value)).text
