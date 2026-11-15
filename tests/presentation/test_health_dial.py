"""HealthDial: the dashboard's centre dial, split by each count's share."""
from django.test import SimpleTestCase

from app.application.project_health_counts import ProjectHealthCounts
from app.domain.score_representation import ScoreTone
from app.presentation.health_dial import HealthDial


class HealthDialTests(SimpleTestCase):
    def test_segments_follow_each_counts_share_with_gaps(self):
        segments = HealthDial.segments(ProjectHealthCounts(failed=1, needs_attention=1, healthy=2))

        self.assertEqual([s.tone for s in segments], [ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY])
        self.assertEqual([s.start for s in segments], [0, 25.5, 51.0])
        self.assertEqual([s.length for s in segments], [24.5, 24.5, 49.0])

    def test_a_zero_count_gets_no_segment(self):
        [segment] = HealthDial.segments(ProjectHealthCounts(failed=0, needs_attention=0, healthy=3))

        self.assertEqual((segment.tone, segment.start, segment.length), (ScoreTone.HEALTHY, 0, 100))

    def test_no_projects_no_segments(self):
        self.assertEqual(HealthDial.segments(ProjectHealthCounts(failed=0, needs_attention=0, healthy=0)), [])
