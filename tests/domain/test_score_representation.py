"""Every score is shown through one representation (SCORE_REPRESENTATION):
today a whole number out of 100, in a tone from the health thresholds,
critical when a Required standard failed, and a dash when there is none."""
from django.test import SimpleTestCase

from app.domain.score_representation import (
    SCORE_REPRESENTATION,
    NumberScoreRepresentation,
    RepresentedScore,
)


class NumberScoreRepresentationTests(SimpleTestCase):
    def test_numbers_are_the_representation_in_use(self):
        assert isinstance(SCORE_REPRESENTATION, NumberScoreRepresentation)

    def test_a_score_reads_as_a_whole_number_in_its_tone(self):
        assert SCORE_REPRESENTATION.represent(82) == RepresentedScore("82", "healthy", "Score 82 out of 100")
        assert SCORE_REPRESENTATION.represent(64.6).text == "65"
        assert SCORE_REPRESENTATION.represent(50).tone == "warning"
        assert SCORE_REPRESENTATION.represent(49).tone == "critical"

    def test_a_score_a_required_standard_failed_is_critical(self):
        assert SCORE_REPRESENTATION.represent(0, failed=True).tone == "critical"

    def test_no_score_is_a_dash(self):
        assert SCORE_REPRESENTATION.represent(None) == RepresentedScore("—", "unknown", "No score yet")


class ToneThresholdsTests(SimpleTestCase):
    def test_health_levels_are_the_score_tones_from_one_set_of_thresholds(self):
        from app.domain import health
        from app.domain.score_representation import ScoreTone

        assert health.level_from_score(80) is ScoreTone.HEALTHY
        assert health.level_from_score(79) is ScoreTone.WARNING
        assert health.level_from_score(None) is ScoreTone.UNKNOWN
        assert health.CRITICAL is ScoreTone.CRITICAL
