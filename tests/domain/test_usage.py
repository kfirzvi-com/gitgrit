"""Workspace usage: the months it is counted over and how a month adds up."""
from datetime import date

from django.test import SimpleTestCase

from app.domain.usage import BillingMonth, DayUsage, MonthUsage

NOV = BillingMonth(2026, 11)


class BillingMonthTests(SimpleTestCase):
    def test_a_month_knows_its_bounds(self):
        self.assertEqual((NOV.first_day, NOV.last_day, NOV.length), (date(2026, 11, 1), date(2026, 11, 30), 30))

    def test_february_in_a_leap_year(self):
        self.assertEqual(BillingMonth(2028, 2).length, 29)

    def test_months_roll_over_the_year(self):
        self.assertEqual(BillingMonth(2026, 12).next(), BillingMonth(2027, 1))
        self.assertEqual(BillingMonth(2027, 1).previous(), BillingMonth(2026, 12))

    def test_a_day_belongs_to_its_month(self):
        self.assertEqual(BillingMonth.of(date(2026, 11, 20)), NOV)

    def test_reads_as_a_label_and_a_key(self):
        self.assertEqual((NOV.label, str(NOV)), ("November 2026", "2026-11"))


class MonthUsageTests(SimpleTestCase):
    def _month(self, *days):
        return MonthUsage(NOV, tuple(DayUsage(date(2026, 11, d), runs, projects) for d, runs, projects in days))

    def test_executions_add_up_over_the_month(self):
        self.assertEqual(self._month((1, 10, 2), (5, 30, 3)).executions, 40)

    def test_projects_count_at_their_peak(self):
        """A project added and removed within the month still used a slot."""
        self.assertEqual(self._month((1, 0, 2), (5, 0, 4), (9, 0, 3)).peak_projects, 4)

    def test_an_empty_month_is_zero(self):
        month = MonthUsage(NOV)

        self.assertEqual((month.executions, month.peak_projects), (0, 0))

    def test_every_day_is_listed_empty_ones_included(self):
        daily = self._month((3, 7, 1)).daily()

        self.assertEqual(len(daily), 30)
        self.assertEqual([d.executions for d in daily[:4]], [0, 0, 7, 0])

    def test_a_day_from_another_month_is_refused(self):
        with self.assertRaises(ValueError):
            MonthUsage(NOV, (DayUsage(date(2026, 12, 1), 1, 1),))

    def test_projects_the_month_at_its_pace_so_far(self):
        month = self._month((1, 100, 1), (10, 200, 1))

        self.assertEqual(month.projected_executions(date(2026, 11, 10)), 900)  # 300 in 10 of 30 days

    def test_a_past_month_projects_what_it_counted(self):
        self.assertEqual(self._month((1, 100, 1)).projected_executions(date(2026, 12, 4)), 100)

    def test_a_month_not_started_projects_nothing(self):
        self.assertEqual(MonthUsage(NOV).projected_executions(date(2026, 10, 30)), 0)
