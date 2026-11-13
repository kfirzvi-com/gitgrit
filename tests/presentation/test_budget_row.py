"""BudgetRow: a budget's window and when it resets."""
from django.test import SimpleTestCase

from app.domain.ai_usage import TokenCount
from app.domain.models import LLMBudget
from app.presentation.budget_row import BudgetRow


class BudgetRowWindowTests(SimpleTestCase):
    def test_the_window_and_when_it_resets(self):
        from datetime import datetime

        wednesday = datetime(2026, 11, 11, 15, 30)
        month = BudgetRow(LLMBudget(period="month", input_limit=1), TokenCount(), now=wednesday)
        day = BudgetRow(LLMBudget(period="day", input_limit=1), TokenCount(), now=wednesday)

        self.assertEqual((month.window, month.resets), ("Nov 1 – Nov 30", datetime(2026, 12, 1)))
        self.assertEqual((day.window, day.resets), ("Nov 11", datetime(2026, 11, 12)))
        self.assertEqual((month.resets_short, day.resets_short), ("Dec 1", "midnight"))
        week = BudgetRow(LLMBudget(period="week", input_limit=1), TokenCount(), now=wednesday)
        self.assertEqual(week.resets_short, "Mon")
