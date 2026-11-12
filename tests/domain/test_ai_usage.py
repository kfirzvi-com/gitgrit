"""The AI usage domain: token counts, budget periods, budget rules and the
standard distribution."""
from datetime import datetime

from django.test import SimpleTestCase

from app.domain.ai_usage import (
    BudgetLevel,
    BudgetPeriod,
    StandardUsage,
    StandardUsageDistribution,
    TokenBudget,
    TokenCount,
)

WEDNESDAY = datetime(2026, 11, 11, 15, 30)


class TokenCountTests(SimpleTestCase):
    def test_counts_add_and_keep_input_and_output_apart(self):
        total = TokenCount.total_of([TokenCount(100, 10, 1), TokenCount(50, 5, 2)])

        self.assertEqual((total.input, total.output, total.calls, total.total), (150, 15, 3, 165))

    def test_counts_are_never_negative(self):
        with self.assertRaises(ValueError):
            TokenCount(-1, 0)


class BudgetPeriodTests(SimpleTestCase):
    def test_each_period_starts_and_ends_on_its_calendar_boundary(self):
        self.assertEqual(BudgetPeriod.DAY.starts(WEDNESDAY), datetime(2026, 11, 11))
        self.assertEqual(BudgetPeriod.WEEK.starts(WEDNESDAY), datetime(2026, 11, 9))  # Monday
        self.assertEqual(BudgetPeriod.MONTH.starts(WEDNESDAY), datetime(2026, 11, 1))
        self.assertEqual(BudgetPeriod.WEEK.ends(WEDNESDAY), datetime(2026, 11, 16))
        self.assertEqual(BudgetPeriod.MONTH.ends(datetime(2026, 12, 31, 23)), datetime(2027, 1, 1))

    def test_the_last_day_of_each_window(self):
        from datetime import date

        self.assertEqual(BudgetPeriod.DAY.last_day(WEDNESDAY), date(2026, 11, 11))
        self.assertEqual(BudgetPeriod.WEEK.last_day(WEDNESDAY), date(2026, 11, 15))
        self.assertEqual(BudgetPeriod.MONTH.last_day(WEDNESDAY), date(2026, 11, 30))

    def test_a_key_names_the_window(self):
        self.assertEqual(BudgetPeriod.WEEK.key(WEDNESDAY), "2026-11-09")
        self.assertNotEqual(BudgetPeriod.DAY.key(WEDNESDAY), BudgetPeriod.DAY.key(datetime(2026, 11, 12)))


class TokenBudgetTests(SimpleTestCase):
    def test_a_budget_is_as_used_as_its_most_used_limit(self):
        budget = TokenBudget(BudgetPeriod.DAY, input_limit=1000, output_limit=100, low_at_percent=20)

        self.assertEqual(budget.level(TokenCount(100, 10)), BudgetLevel.OK)
        self.assertEqual(budget.level(TokenCount(100, 85)), BudgetLevel.NEAR)  # output at 85%
        self.assertEqual(budget.level(TokenCount(1000, 0)), BudgetLevel.REACHED)

    def test_the_low_mark_is_the_budgets_own_and_optional(self):
        used = TokenCount(75, 0)

        self.assertEqual(TokenBudget(BudgetPeriod.DAY, input_limit=100, low_at_percent=30).level(used), BudgetLevel.NEAR)
        self.assertEqual(TokenBudget(BudgetPeriod.DAY, input_limit=100, low_at_percent=10).level(used), BudgetLevel.OK)
        no_warning = TokenBudget(BudgetPeriod.DAY, input_limit=100)
        self.assertEqual(no_warning.level(TokenCount(99, 0)), BudgetLevel.OK)
        self.assertEqual(no_warning.to_announce(TokenCount(99, 0), BudgetLevel.OK), None)
        self.assertEqual(no_warning.to_announce(TokenCount(100, 0), BudgetLevel.OK), BudgetLevel.REACHED)

    def test_the_low_mark_is_a_percentage_below_100(self):
        for bad in (0, 100, 150):
            with self.assertRaises(ValueError):
                TokenBudget(BudgetPeriod.DAY, input_limit=100, low_at_percent=bad)

    def test_an_unset_limit_is_ignored(self):
        budget = TokenBudget(BudgetPeriod.DAY, output_limit=100)

        self.assertEqual(budget.level(TokenCount(10_000_000, 10)), BudgetLevel.OK)

    def test_a_budget_needs_a_positive_limit(self):
        with self.assertRaises(ValueError):
            TokenBudget(BudgetPeriod.DAY)
        with self.assertRaises(ValueError):
            TokenBudget(BudgetPeriod.DAY, input_limit=0)

    def test_only_a_stop_at_limit_budget_stops_runs_and_only_when_reached(self):
        used_up = TokenCount(100, 0)
        self.assertTrue(TokenBudget(BudgetPeriod.DAY, input_limit=100, stop_at_limit=True).stops_runs(used_up))
        self.assertFalse(TokenBudget(BudgetPeriod.DAY, input_limit=100).stops_runs(used_up))
        self.assertFalse(TokenBudget(BudgetPeriod.DAY, input_limit=200, stop_at_limit=True).stops_runs(used_up))

    def test_each_level_is_announced_once_and_never_a_step_back(self):
        budget = TokenBudget(BudgetPeriod.DAY, input_limit=100, low_at_percent=20)

        self.assertEqual(budget.to_announce(TokenCount(85, 0), BudgetLevel.OK), BudgetLevel.NEAR)
        self.assertIsNone(budget.to_announce(TokenCount(90, 0), BudgetLevel.NEAR))
        self.assertEqual(budget.to_announce(TokenCount(100, 0), BudgetLevel.NEAR), BudgetLevel.REACHED)
        self.assertIsNone(budget.to_announce(TokenCount(10, 0), BudgetLevel.REACHED))


def _standard(name, total, runs=1):
    return StandardUsage(standard_id=name, name=name, tokens=TokenCount(total, 0, runs), runs=runs)


class StandardUsageDistributionTests(SimpleTestCase):
    def test_standards_are_biggest_first_with_their_share(self):
        dist = StandardUsageDistribution([_standard("a", 100), _standard("b", 300)])

        self.assertEqual([p.name for p in dist.standards], ["b", "a"])
        self.assertEqual(dist.share(dist.standards[0]), 0.75)

    def test_a_standard_spending_twice_the_median_is_heavy(self):
        dist = StandardUsageDistribution([_standard("a", 100), _standard("b", 110), _standard("c", 120), _standard("big", 500)])

        self.assertEqual([p.name for p in dist.heavy], ["big"])
        self.assertEqual(dist.times_median(dist.standards[0]), 4.3)

    def test_too_few_standards_have_no_heavy_one(self):
        self.assertEqual(StandardUsageDistribution([_standard("a", 10), _standard("b", 1000)]).heavy, [])

    def test_per_run_average(self):
        self.assertEqual(_standard("a", 900, runs=3).per_run, 300)


class BudgetSummaryTests(SimpleTestCase):
    def test_counts_budgets_by_how_far_used_and_which_stop_runs(self):
        from app.domain.ai_usage import BudgetSummary

        def budget(stop=False):
            return TokenBudget(BudgetPeriod.DAY, input_limit=100, stop_at_limit=stop, low_at_percent=20)

        summary = BudgetSummary.of([
            (budget(), TokenCount(10, 0)),
            (budget(), TokenCount(85, 0)),
            (budget(stop=True), TokenCount(120, 0)),
        ])

        self.assertEqual((summary.ok, summary.near, summary.used_up, summary.stopping, summary.total), (1, 1, 1, 1, 3))
        self.assertEqual(summary.worst, BudgetLevel.REACHED)



class ModelAccessTests(SimpleTestCase):
    def test_budgets_are_an_allow_list(self):
        from app.domain.ai_usage import Denial, ModelAccess

        budget = TokenBudget(BudgetPeriod.DAY, input_limit=100, stop_at_limit=True)
        warn_only = TokenBudget(BudgetPeriod.WEEK, input_limit=100)

        self.assertEqual(ModelAccess.of([]).denial, Denial.NO_BUDGET)
        self.assertTrue(ModelAccess.of([(budget, TokenCount(10, 0))]).allowed)
        self.assertTrue(ModelAccess.of([(warn_only, TokenCount(500, 0))]).allowed)  # over, but only warns
        stopped = ModelAccess.of([(warn_only, TokenCount(0, 0)), (budget, TokenCount(100, 0))])
        self.assertEqual((stopped.denial, stopped.budget), (Denial.USED_UP, 1))
