"""Workspace usage: the months it is counted over and how a month adds up."""
from datetime import date

from django.test import SimpleTestCase

from app.domain.usage import BillingMonth, Breakdown, DayUsage, ExecutionSlice, MonthUsage, Share

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

    def test_parses_its_key(self):
        self.assertEqual(BillingMonth.parse("2026-11"), NOV)
        self.assertEqual([BillingMonth.parse(t) for t in ("", "2026-13", "nov")], [None, None, None])

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

    def test_the_daily_average_counts_the_days_so_far(self):
        month = self._month((1, 100, 1), (10, 200, 1))

        self.assertEqual(month.daily_average(date(2026, 11, 10)), 30)
        self.assertEqual(month.daily_average(date(2026, 12, 1)), 10)

    def test_run_time_adds_up_and_projects_at_its_pace(self):
        month = MonthUsage(NOV, (DayUsage(date(2026, 11, 1), 4, 1, run_ms=120_000, timed_runs=4),
                                 DayUsage(date(2026, 11, 2), 2, 1, run_ms=60_000, timed_runs=2)))

        self.assertEqual(month.minutes, 3)
        self.assertEqual(month.projected_minutes(date(2026, 11, 2)), 45)  # 3 min in 2 of 30 days
        self.assertEqual(month.average_run_seconds, 30)

    def test_the_average_run_counts_only_timed_runs(self):
        """The day timing began also has runs from before it: 7 runs, 5 timed."""
        month = MonthUsage(NOV, (DayUsage(date(2026, 11, 1), 100, 1),
                                 DayUsage(date(2026, 11, 2), 7, 1, run_ms=75_000, timed_runs=5)))

        self.assertEqual(month.average_run_seconds, 15)

    def test_running_totals_climb_through_the_month(self):
        self.assertEqual(self._month((1, 5, 1), (3, 2, 1)).running_totals()[:4], [5, 5, 7, 7])


def _slice(project, trigger, n):
    return ExecutionSlice(project, f"acme/{project}", trigger, n)


class BreakdownTests(SimpleTestCase):
    def test_splits_by_project_biggest_first(self):
        breakdown = Breakdown([_slice("api", "push", 2), _slice("web", "push", 5), _slice("api", "manual", 1)])

        self.assertEqual(breakdown.by_project(), [Share("acme/web", 5), Share("acme/api", 3)])

    def test_splits_by_trigger_biggest_first(self):
        breakdown = Breakdown([_slice("api", "push", 2), _slice("web", "push", 5), _slice("api", "manual", 1)])

        self.assertEqual(breakdown.by_trigger(), [Share("push", 7), Share("manual", 1)])

    def test_run_time_adds_up_with_the_executions(self):
        breakdown = Breakdown([ExecutionSlice("api", "acme/api", "push", 2, 90_000),
                               ExecutionSlice("api", "acme/api", "manual", 1, 30_000)])

        self.assertEqual(breakdown.by_project(), [Share("acme/api", 3, 120_000)])
        self.assertEqual(breakdown.by_project()[0].minutes, 2)

    def test_run_time_finishing_on_a_later_day_still_shows(self):
        """A run queued before midnight can finish after it: time, no executions."""
        self.assertEqual(Breakdown([ExecutionSlice("api", "acme/api", "push", 0, 5_000)]).by_trigger(),
                         [Share("push", 0, 5_000)])

    def test_a_month_splits_across_its_days(self):
        month = MonthUsage(NOV, (DayUsage(date(2026, 11, 1), 2, 1, slices=(_slice("api", "push", 2),)),
                                 DayUsage(date(2026, 11, 2), 3, 1, slices=(_slice("api", "push", 3),))))

        self.assertEqual(month.breakdown.by_project(), [Share("acme/api", 5)])
