"""Templates show scores through one tag, so they read the same everywhere."""
from django.template import Context, Template
from django.test import SimpleTestCase


def render(source, **context):
    return Template("{% load score_tags %}" + source).render(Context(context))


class ScoreTagTests(SimpleTestCase):
    def test_the_score_tag_shows_the_text_in_its_tone(self):
        html = render('{% score value size="lg" %}', value=82)
        assert ">82</span>" in html
        assert "gg-tone-text-healthy" in html
        assert 'aria-label="Score 82 out of 100"' in html

    def test_a_failed_score_is_red(self):
        assert "gg-tone-text-critical" in render("{% score 0 failed=True %}")

    def test_score_text_is_the_bare_text(self):
        assert render("{{ value|score_text }}", value=None) == "—"


class ScoreToneStylesTests(SimpleTestCase):
    def test_every_tone_has_one_colour_used_by_css_and_the_diagrams(self):
        from app.domain.score_representation import ScoreTone
        from app.presentation.score_tones import ScoreToneStyle

        html = render("{% score_tone_styles %}")
        for tone in ScoreTone:
            color = ScoreToneStyle.for_tone(tone).color
            assert f"--gg-tone-{tone}: {color};" in html
            assert f".gg-tone-text-{tone}" in html
        assert 'id="gg-score-tones"' in html
        assert ScoreToneStyle.as_json()["critical"] == {"color": "#f87171", "label": "Critical"}

    def test_the_api_level_choices_are_the_score_tones(self):
        from app.domain.score_representation import ScoreTone
        from app.presentation.api.serializers import LEVEL_CHOICES

        assert LEVEL_CHOICES == [t.value for t in ScoreTone]
