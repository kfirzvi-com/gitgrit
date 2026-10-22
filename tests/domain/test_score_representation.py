"""A commit's score reads as a letter (COMMIT_SCORE_REPRESENTATION: A+ 100,
A 90+, B 75+, C 60+, D below; F only when a Required standard failed); one
standard's result reads as a number (STANDARD_RESULT_REPRESENTATION). Every
score's health comes from one rule (ScoreHealth): healthy from 90, needs
attention below, failed only for a Required failure. A dash for no score."""
from django.test import SimpleTestCase

from app.domain.score_representation import (
    COMMIT_SCORE_REPRESENTATION,
    STANDARD_RESULT_REPRESENTATION,
    LetterScoreRepresentation,
    NumberScoreRepresentation,
    RepresentedScore,
    ScoreBands,
    ScoreHealth,
    ScoreTone,
)


class LetterScoreRepresentationTests(SimpleTestCase):
    def test_a_commit_score_reads_as_a_letter_and_a_standard_result_as_a_number(self):
        assert isinstance(COMMIT_SCORE_REPRESENTATION, LetterScoreRepresentation)
        assert isinstance(STANDARD_RESULT_REPRESENTATION, NumberScoreRepresentation)
        assert (COMMIT_SCORE_REPRESENTATION.represent(82).text, STANDARD_RESULT_REPRESENTATION.represent(82).text) == ("B", "82")

    def test_bands(self):
        letters = LetterScoreRepresentation()
        cases = [(100, "A+"), (99, "A"), (90, "A"), (89, "B"), (75, "B"), (74, "C"), (60, "C"), (59, "D"), (0, "D")]
        for value, expected in cases:
            with self.subTest(value=value):
                assert letters.represent(value).text == expected

    def test_a_and_above_are_healthy_b_to_d_need_attention(self):
        letters = LetterScoreRepresentation()
        assert [letters.represent(v).tone for v in (100, 95, 80, 65, 10)] == [
            ScoreTone.HEALTHY, ScoreTone.HEALTHY,
            ScoreTone.NEEDS_ATTENTION, ScoreTone.NEEDS_ATTENTION, ScoreTone.NEEDS_ATTENTION,
        ]

    def test_the_scale_lists_each_letter_with_its_health_and_shade(self):
        assert [(s.text, s.tone, s.shade) for s in LetterScoreRepresentation().scale()] == [
            ("A+", ScoreTone.HEALTHY, "healthy"), ("A", ScoreTone.HEALTHY, "healthy"),
            ("B", ScoreTone.NEEDS_ATTENTION, "needs_attention"), ("C", ScoreTone.NEEDS_ATTENTION, "needs_attention"),
            ("D", ScoreTone.NEEDS_ATTENTION, "low"), ("F", ScoreTone.FAILED, "failed"),
        ]

    def test_a_d_is_painted_orange_but_still_needs_attention(self):
        d = LetterScoreRepresentation().represent(40)
        assert (d.text, d.tone, d.shade) == ("D", ScoreTone.NEEDS_ATTENTION, "low")
        assert d.as_dict() == {"text": "D", "tone": "needs_attention", "spoken": "Grade D, score 40 out of 100"}

    def test_f_only_when_a_required_standard_failed(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(0).text == "D"
        assert COMMIT_SCORE_REPRESENTATION.represent(0, failed=True) == RepresentedScore(
            "F", ScoreTone.FAILED, "Failed: a Required standard failed"
        )
        # A failed commit has no number to show: still an F.
        assert COMMIT_SCORE_REPRESENTATION.represent(None, failed=True).text == "F"

    def test_spoken(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(82).spoken == "Grade B, score 82 out of 100"

    def test_no_score_is_a_dash(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(None) == RepresentedScore("—", ScoreTone.UNKNOWN, "No score yet")


class NumberScoreRepresentationTests(SimpleTestCase):
    def test_a_score_reads_as_a_whole_number_with_the_same_health_as_letters(self):
        numbers = NumberScoreRepresentation()
        assert numbers.represent(92) == RepresentedScore("92", ScoreTone.HEALTHY, "Score 92 out of 100")
        assert numbers.represent(64.6).text == "65"
        assert numbers.represent(89).tone is ScoreTone.NEEDS_ATTENTION
        # A failed commit reads F in every representation: a verdict, not a score.
        assert numbers.represent(0, failed=True) == RepresentedScore(
            "F", ScoreTone.FAILED, "Failed: a Required standard failed"
        )


class HealthLevelsTests(SimpleTestCase):
    def test_health_levels_are_the_tones_of_the_representation_in_use(self):
        from app.domain import health

        assert health.level_from_score(95) is ScoreTone.HEALTHY
        assert health.level_from_score(80) is ScoreTone.NEEDS_ATTENTION
        assert health.level_from_score(0) is ScoreTone.NEEDS_ATTENTION
        assert health.level_from_score(0, failed=True) is ScoreTone.FAILED
        assert health.level_from_score(None) is ScoreTone.UNKNOWN
        assert health.worst([ScoreTone.NEEDS_ATTENTION, ScoreTone.FAILED, ScoreTone.HEALTHY]) is ScoreTone.FAILED


class ScoreHealthTests(SimpleTestCase):
    """One rule for every score: healthy from 90, needs attention below,
    failed only when a Required standard failed."""

    def test_one_threshold(self):
        assert ScoreHealth.HEALTHY_FROM == 90
        assert (ScoreHealth.tone(90), ScoreHealth.tone(89)) == (ScoreTone.HEALTHY, ScoreTone.NEEDS_ATTENTION)

    def test_failed_whatever_the_number_and_unknown_without_one(self):
        assert ScoreHealth.tone(100, failed=True) is ScoreTone.FAILED
        assert ScoreHealth.tone(None, failed=True) is ScoreTone.FAILED
        assert ScoreHealth.tone(None) is ScoreTone.UNKNOWN

    def test_a_low_score_is_never_failed(self):
        assert not ScoreHealth.tone(0).is_failed
        assert ScoreHealth.tone(0).needs_attention


class SharedScaleTests(SimpleTestCase):
    """Every representation reads the same bands, one-to-one (ScoreBands):
    the same steps, in the same order and colours, and F for failed. A new
    representation only says how a band is written."""

    REPRESENTATIONS = (LetterScoreRepresentation(), NumberScoreRepresentation())

    def test_every_representation_has_the_same_categories_and_colours(self):
        scales = [[(s.tone, s.shade) for s in r.scale()] for r in self.REPRESENTATIONS]
        assert len({tuple(scale) for scale in scales}) == 1
        assert len(scales[0]) == len(ScoreBands.BANDS) + 1

    def test_letters_and_numbers_map_one_to_one(self):
        letters, numbers = (r.scale() for r in self.REPRESENTATIONS)
        assert [(l.text, n.text) for l, n in zip(letters, numbers)] == [
            ("A+", "100"), ("A", "90–99"), ("B", "75–89"), ("C", "60–74"), ("D", "0–59"), ("F", "F"),
        ]

    def test_a_score_lights_the_same_step_in_both(self):
        letters, numbers = self.REPRESENTATIONS
        for value in (100, 95, 82, 64, 12):
            with self.subTest(value=value):
                assert ScoreBands.of(value).range_text == numbers.scale_step_of(value)
                assert ScoreBands.of(value).letter == letters.scale_step_of(value)
        assert letters.scale_step_of(None, failed=True) == numbers.scale_step_of(None, failed=True) == "F"

    def test_a_number_below_60_is_orange_like_a_d(self):
        assert NumberScoreRepresentation().represent(40).shade == LetterScoreRepresentation().represent(40).shade == "low"

    def test_healthy_starts_at_the_a_band(self):
        assert ScoreHealth.HEALTHY_FROM == ScoreBands.of(90).lowest == 90
