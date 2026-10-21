"""A commit's score reads as a letter (COMMIT_SCORE_REPRESENTATION: A+ 100,
A 90+, B 75+, C 60+, D below; F only when a Required standard failed), each
letter in its own band; one standard's result reads as a number
(STANDARD_RESULT_REPRESENTATION). A dash when there is no score."""
from django.test import SimpleTestCase

from app.domain.score_representation import (
    COMMIT_SCORE_REPRESENTATION,
    STANDARD_RESULT_REPRESENTATION,
    LetterScoreRepresentation,
    NumberScoreRepresentation,
    RepresentedScore,
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

    def test_each_letter_has_its_band(self):
        letters = LetterScoreRepresentation()
        assert [letters.represent(v).tone for v in (100, 95, 80, 65, 10)] == [
            ScoreTone.HEALTHY, ScoreTone.HEALTHY, ScoreTone.WARNING, ScoreTone.CAUTION, ScoreTone.CRITICAL,
        ]

    def test_f_only_when_a_required_standard_failed(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(0).text == "D"
        assert COMMIT_SCORE_REPRESENTATION.represent(0, failed=True) == RepresentedScore(
            "F", ScoreTone.SEVERE, "Grade F: a Required standard failed"
        )

    def test_spoken(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(82).spoken == "Grade B, score 82 out of 100"

    def test_no_score_is_a_dash(self):
        assert COMMIT_SCORE_REPRESENTATION.represent(None) == RepresentedScore("—", ScoreTone.UNKNOWN, "No score yet")


class NumberScoreRepresentationTests(SimpleTestCase):
    def test_a_score_reads_as_a_whole_number_in_its_tone(self):
        numbers = NumberScoreRepresentation()
        assert numbers.represent(82) == RepresentedScore("82", ScoreTone.HEALTHY, "Score 82 out of 100")
        assert numbers.represent(64.6).text == "65"
        assert numbers.represent(50).tone is ScoreTone.WARNING
        assert numbers.represent(49).tone is ScoreTone.CRITICAL
        assert numbers.represent(0, failed=True).tone is ScoreTone.SEVERE


class HealthLevelsTests(SimpleTestCase):
    def test_health_levels_are_the_tones_of_the_representation_in_use(self):
        from app.domain import health

        assert health.level_from_score(95) is ScoreTone.HEALTHY
        assert health.level_from_score(80) is ScoreTone.WARNING
        assert health.level_from_score(0, failed=True) is ScoreTone.SEVERE
        assert health.level_from_score(None) is ScoreTone.UNKNOWN
        assert health.worst([ScoreTone.CAUTION, ScoreTone.SEVERE, ScoreTone.HEALTHY]) is ScoreTone.SEVERE
