"""Templates show scores through one tag, so they read the same everywhere."""
from django.template import Context, Template
from django.test import SimpleTestCase


def render(source, **context):
    return Template("{% load score_tags %}" + source).render(Context(context))


class ScoreTagTests(SimpleTestCase):
    def test_the_score_tag_shows_the_text_in_its_tone(self):
        html = render('{% score value size="lg" %}', value=82)
        assert ">B</span>" in html
        assert "gg-tone-text-needs_attention" in html
        assert 'aria-label="Grade B, score 82 out of 100"' in html

    def test_a_failed_score_is_red(self):
        html = render("{% score 0 failed=True %}")
        assert ">F</span>" in html and "gg-tone-text-failed" in html and "gg-score-failed" in html

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
        assert ScoreToneStyle.as_json()["failed"] == {"color": "#ef4444", "label": "Failed"}

    def test_the_api_level_choices_are_the_score_tones(self):
        from app.domain.score_representation import ScoreTone
        from app.presentation.api.serializers import LEVEL_CHOICES

        assert LEVEL_CHOICES == [t.value for t in ScoreTone]


class MissingScoreTests(SimpleTestCase):
    def test_a_missing_value_reads_as_no_score(self):
        assert ">—</span>" in render("{% score project.commit_score.value %}", project=object())
        assert render("{% score_tone missing.value as tone %}{{ tone }}") == "unknown"


class LowShadeTests(SimpleTestCase):
    def test_a_d_reads_orange(self):
        from app.presentation.score_tones import ScoreToneStyle

        html = render('{% score value %}', value=40)
        assert ">D</span>" in html and "gg-tone-text-low" in html
        assert ScoreToneStyle.for_tone("low") == ScoreToneStyle("low", "#fb923c", "Needs attention")
