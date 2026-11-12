"""FuelGauge: a tank per budgeted model, filled to what is left."""
from django.test import SimpleTestCase

from app.domain.ai_usage import BudgetLevel, TokenCount
from app.domain.models import LLMBudget
from app.presentation.budget_row import BudgetRow
from app.presentation.fuel_gauge import TANKS_SHOWN, FuelGauge


def _row(limit, used, model="m", period="month"):
    return BudgetRow(LLMBudget(model=model, period=period, input_limit=limit, low_at_percent=20), TokenCount(used, 0))


class FuelGaugeTests(SimpleTestCase):
    def test_a_tank_per_budget_emptiest_first(self):
        gauge = FuelGauge([_row(1000, 100, "a"), _row(100, 85, "b"), _row(100, 150, "c")])

        self.assertEqual(
            [(t.row.budget.model, t.percent_left, t.level) for t in gauge.tanks],
            [("c", 0, BudgetLevel.REACHED), ("b", 15, BudgetLevel.NEAR), ("a", 90, BudgetLevel.OK)],
        )
        self.assertEqual(gauge.summary.total, 3)

    def test_extra_budgets_are_counted(self):
        gauge = FuelGauge([_row(100, i, str(i)) for i in range(TANKS_SHOWN + 2)])

        self.assertEqual((len(gauge.tanks), gauge.more), (TANKS_SHOWN, 2))

    def test_no_budget_no_tanks(self):
        self.assertFalse(FuelGauge([]).has_budget)
