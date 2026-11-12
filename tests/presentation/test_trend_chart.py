"""TrendChart: where the healthy-projects trend draws."""
from datetime import date

from django.test import SimpleTestCase

from app.application.cockpit import TrendPoint
from app.presentation.trend_chart import TrendChart


class TrendChartTests(SimpleTestCase):
    def test_points_span_the_chart_on_a_zero_to_total_scale(self):
        chart = TrendChart([TrendPoint(date(2026, 10, 14), 2, 4), TrendPoint(date(2026, 10, 21), 4, 4)])

        self.assertEqual([(p.x, p.y, p.label) for p in chart.healthy], [(40, 110.0, "Oct 14"), (540, 20.0, "Oct 21")])
        self.assertEqual((chart.change, chart.this_week), (2, 2))
        self.assertEqual(chart.ticks[0], (20.0, 4))

    def test_no_projects_still_draws_a_flat_line(self):
        chart = TrendChart([TrendPoint(date(2026, 10, 14), 0, 0)])

        self.assertEqual([(p.x, p.y) for p in chart.healthy], [(290.0, 200.0)])
        self.assertEqual(chart.change, 0)
