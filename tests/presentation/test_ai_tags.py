"""ai_tags: token counts and short model names."""
from django.test import SimpleTestCase

from app.templatetags.ai_tags import percent, short_model, tokens


class AITagsTests(SimpleTestCase):
    def test_tokens(self):
        self.assertEqual([tokens(950), tokens(12_400), tokens(3_100_000), tokens(None)], ["950", "12.4k", "3.1M", "0"])

    def test_percent_caps_at_a_full_bar(self):
        self.assertEqual([percent(0.426), percent(1.7)], [43, 100])

    def test_short_model(self):
        self.assertEqual(
            [short_model(m) for m in ("claude-haiku-4-5-20251001", "claude-opus-4-1", "gpt-5-mini", "gemini-2.5-flash", "anthropic/claude-sonnet-4-5")],
            ["haiku 4.5", "opus 4.1", "gpt-5 mini", "gemini 2.5 flash", "sonnet 4.5"],
        )
