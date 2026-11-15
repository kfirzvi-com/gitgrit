"""Recording AI usage and keeping it inside budgets."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.ai_usage import AIUsageReport, BudgetWatch, UsageRecorder
from app.domain.ai_usage import BudgetPeriod, TokenCount, UsageCategory
from app.domain.models import LLMBudget, LLMUsage, Notification
from app.domain.notifications import Kind

RAISE = "app.application.notifications.service.raise_notification"


class UsageTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.provider = baker.make("app.LLMProvider", tenant=self.tenant, display_name="Anthropic", api_key="k")

    def _record(self, i, o, model="haiku", category=UsageCategory.STANDARD, **kw):
        return UsageRecorder.record(tenant=self.tenant, provider_id=self.provider.pk, model=model,
                                    category=category, tokens=TokenCount(i, o, 1), **kw)

    def _budget(self, **kw):
        defaults = dict(tenant=self.tenant, provider=self.provider, model="haiku", period="day", input_limit=1000)
        return LLMBudget.objects.create(**{**defaults, **kw})


class UsageRecorderTests(UsageTests):
    def test_records_input_and_output_apart_with_the_provider_name(self):
        usage = self._record(120, 30)

        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.provider_name), (120, 30, "Anthropic"))

    def test_nothing_spent_records_nothing(self):
        self.assertIsNone(UsageRecorder.record(tenant=self.tenant, provider_id=None, model="x",
                                               category=UsageCategory.MAP, tokens=TokenCount()))

    def test_a_standard_run_bills_each_model_it_used(self):
        execution = baker.make("app.StandardExecution", project__tenant=self.tenant, standard__name="Docs")
        UsageRecorder.record_standard_run(execution, {
            "by_model": {
                "anthropic/haiku": {"provider_id": str(self.provider.pk), "model": "haiku", "prompt_tokens": 100, "completion_tokens": 10, "calls": 2},
                "anthropic/sonnet": {"provider_id": str(self.provider.pk), "model": "sonnet", "prompt_tokens": 50, "completion_tokens": 5, "calls": 1},
            }
        }, {})

        rows = {u.model: (u.input_tokens, u.output_tokens, u.standard_name) for u in LLMUsage.objects.all()}
        self.assertEqual(rows, {"haiku": (100, 10, "Docs"), "sonnet": (50, 5, "Docs")})

    def test_an_older_sandbox_bills_its_totals_to_the_reasoning_model(self):
        execution = baker.make("app.StandardExecution", project__tenant=self.tenant)
        roles = {"reasoning": {"provider_id": str(self.provider.pk), "model_name": "haiku"}}

        UsageRecorder.record_standard_run(execution, {"prompt_tokens": 7, "completion_tokens": 3, "calls": 1}, roles)

        [usage] = LLMUsage.objects.all()
        self.assertEqual((usage.model, usage.input_tokens, usage.output_tokens), ("haiku", 7, 3))


class BudgetWatchTests(UsageTests):
    def test_used_counts_only_the_budgets_model_and_period(self):
        budget = self._budget()
        self._record(100, 10)
        self._record(999, 99, model="sonnet")
        old = self._record(500, 50)
        LLMUsage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))

        self.assertEqual(BudgetWatch.used(budget), TokenCount(100, 10, 1))

    def test_announces_near_then_reached_once_each_per_period(self):
        self._budget(low_at_percent=20)
        with mock.patch(RAISE) as raised:
            self._record(850, 0)  # 85%: near
            self._record(50, 0)  # still near: nothing new
            self._record(100, 0)  # used up

        kinds = [c.args[0].kind for c in raised.call_args_list]
        self.assertEqual(kinds, [Kind.AI_BUDGET_NEAR, Kind.AI_BUDGET_REACHED])

    def test_a_model_without_a_budget_may_not_run(self):
        refusal = BudgetWatch.refusal(self.tenant, self.provider.pk, "haiku")

        self.assertIn("No AI budget for Anthropic haiku", refusal)

    def test_a_model_with_a_budget_runs_until_a_stop_at_limit_budget_is_used_up(self):
        self._budget(stop_at_limit=False)
        weekly = self._budget(period="week", input_limit=100, stop_at_limit=True)
        with mock.patch(RAISE):
            self._record(50, 0)
            self.assertIsNone(BudgetWatch.refusal(self.tenant, self.provider.pk, "haiku"))
            self._record(60, 0)

        self.assertIn("weekly budget", BudgetWatch.refusal(self.tenant, self.provider.pk, "haiku"))
        self.assertIn("weekly budget", BudgetWatch.stop_message(weekly))


class AIUsageReportTests(UsageTests):
    def test_groups_by_provider_and_model_category_and_standard(self):
        baker.make("app.LLMRole", tenant=self.tenant, provider=self.provider, name="code", model="sonnet")
        self._budget(output_limit=100)
        docs = baker.make("app.Standard", tenant=self.tenant, name="Docs")
        with mock.patch(RAISE):
            self._record(100, 10, standard=docs, execution=baker.make("app.StandardExecution", project__tenant=self.tenant))
            self._record(300, 20, category=UsageCategory.MAP)

        report = AIUsageReport.for_workspace(self.tenant, BudgetPeriod.MONTH)

        [provider] = report.providers
        self.assertEqual([(m.model, m.tokens.input) for m in provider.models], [("haiku", 400), ("sonnet", 0)])
        [(budget, used)] = provider.models[0].budgets
        self.assertEqual(used, TokenCount(400, 30, 2))
        self.assertEqual(dict(report.categories)[UsageCategory.MAP], TokenCount(300, 20, 1))
        [standard] = report.standards.standards
        self.assertEqual((standard.name, standard.tokens.total, standard.runs), ("Docs", 110, 1))
        self.assertEqual(report.total.total, 430)


LLM_CODE = "def evaluate(project, llm):\n    return {'passed': True, 'score': 100}\n"
PLAIN_CODE = "def evaluate(project):\n    return {'passed': True, 'score': 100}\n"


class StopAtLimitTests(UsageTests):
    def setUp(self):
        super().setUp()
        self.roles = {"reasoning": {"provider_id": str(self.provider.pk), "model_name": "haiku", "model": "anthropic/haiku"}}
        self._budget(input_limit=100, stop_at_limit=True)
        with mock.patch(RAISE):
            self._record(100, 0)

    def _run(self, code):
        from app.application.standard_engine import StandardEngine

        project = baker.make("app.Project", tenant=self.tenant, platform="github")
        execution = baker.make("app.StandardExecution", project=project, standard__code=code, standard__tenant=self.tenant)
        engine = StandardEngine()
        engine._runner = mock.Mock()
        engine._runner.run.return_value = {"passed": True, "score": 100, "details": {}}
        with mock.patch.object(type(project), "is_artifact", new_callable=mock.PropertyMock, return_value=False):
            engine.run_execution(execution, {"llm_roles": self.roles})
        execution.refresh_from_db()
        return engine, execution

    def test_an_llm_standard_is_held_back_and_says_why(self):
        engine, execution = self._run(LLM_CODE)

        engine._runner.run.assert_not_called()
        self.assertEqual(execution.status, "error")
        self.assertIn("AI budget used up: Anthropic haiku", execution.message)

    def test_an_llm_standard_on_a_model_without_a_budget_is_held_back(self):
        LLMBudget.objects.all().delete()

        engine, execution = self._run(LLM_CODE)

        engine._runner.run.assert_not_called()
        self.assertIn("No AI budget", execution.message)

    def test_a_standard_without_the_llm_still_runs(self):
        engine, execution = self._run(PLAIN_CODE)

        engine._runner.run.assert_called_once()
        self.assertEqual(execution.status, "passed")

    def test_the_dependency_map_is_held_back_too(self):
        from app.application.dependency_agent import infer_and_store
        from app.infrastructure.topology.llm_inference import LLMTopologyInference

        inference = LLMTopologyInference({"model": "anthropic/haiku", "provider_id": str(self.provider.pk), "model_name": "haiku"})
        with self.assertRaisesMessage(RuntimeError, "AI budget used up"):
            infer_and_store(baker.make("app.Project", tenant=self.tenant), inference=inference, snapshot=mock.Mock())


class MapBillingTests(UsageTests):
    def test_a_map_run_bills_its_tokens_even_when_it_fails(self):
        from app.application.dependency_agent import infer_and_store
        from app.infrastructure.topology.llm_inference import LLMTopologyInference

        agent = mock.Mock(usage={"prompt_tokens": 900, "completion_tokens": 40, "calls": 3})
        agent.run.side_effect = RuntimeError("model gave up")
        inference = LLMTopologyInference(
            {"model": "anthropic/haiku", "provider_id": str(self.provider.pk), "model_name": "haiku"},
            agent_factory=lambda log: agent,
        )
        project = baker.make("app.Project", tenant=self.tenant)
        self._budget(input_limit=1_000_000)

        with self.assertRaises(RuntimeError), mock.patch(RAISE):
            infer_and_store(project, inference=inference, snapshot=mock.Mock())

        [usage] = LLMUsage.objects.all()
        self.assertEqual((usage.category, usage.model, usage.input_tokens, usage.output_tokens, usage.project),
                         ("map", "haiku", 900, 40, project))
