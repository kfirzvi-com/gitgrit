"""Templates show scores through one tag, so they read the same everywhere."""
from django.template import Context, Template
from django.test import SimpleTestCase


def render(source, **context):
    return Template("{% load score_tags %}" + source).render(Context(context))


class ScoreTagTests(SimpleTestCase):
    def test_the_score_tag_shows_the_text_in_its_tone(self):
        html = render('{% score value size="lg" %}', value=82)
        assert ">82</span>" in html
        assert "text-success" in html
        assert 'aria-label="Score 82 out of 100"' in html

    def test_a_failed_score_is_red(self):
        assert "text-error" in render("{% score 0 failed=True %}")

    def test_score_text_is_the_bare_text(self):
        assert render("{{ value|score_text }}", value=None) == "—"
