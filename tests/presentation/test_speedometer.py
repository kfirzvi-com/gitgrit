"""Speedometer: a value against a full scale, as arc, needle and ticks."""
from django.test import SimpleTestCase

from app.presentation.speedometer import Speedometer


class SpeedometerTests(SimpleTestCase):
    def test_needle_follows_the_share_of_the_scale(self):
        gauge = Speedometer(90, 100)

        self.assertEqual(gauge.share, 90.0)
        self.assertEqual(gauge.needle, (155.2, 117.9))

    def test_empty_and_full(self):
        self.assertEqual(Speedometer(0, 0).needle, (59.0, 141.0))
        self.assertEqual(Speedometer(5, 5).share, 100.0)

    def test_a_round_gauge_draws_the_long_arc_and_a_shallow_one_the_short(self):
        self.assertIn(" 0 1 1 ", Speedometer(1, 2).arc_path)
        self.assertIn(" 0 0 1 ", Speedometer(1, 2, start=160, sweep=140).arc_path)
        self.assertEqual(len(Speedometer(1, 2, ticks=5).ticks), 5)
