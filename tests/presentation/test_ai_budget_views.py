"""AI budgets in workspace settings: owners and admins set them; members see them."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import LLMBudget

NON_MANIFEST_STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
HTMX = {"HTTP_HX_REQUEST": "true"}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class AIBudgetViewTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.provider = baker.make("app.LLMProvider", tenant=self.tenant, display_name="Anthropic", api_key="k",
                                   available_models=["haiku", "sonnet"])
        baker.make("app.LLMRole", tenant=self.tenant, provider=self.provider, name="reasoning", model="haiku")

    def _login(self, role):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _save(self, **fields):
        data = {"model_key": f"{self.provider.pk}|haiku", "period": "week", "input_limit": "1,000,000", "output_limit": ""}
        return self.client.post(reverse("save_ai_budget"), {**data, **fields}, **HTMX)

    def test_an_admin_sets_a_budget_in_place(self):
        self._login("admin")

        response = self._save(stop_at_limit="on")

        budget = LLMBudget.objects.get()
        self.assertEqual((budget.model, budget.period, budget.input_limit, budget.output_limit, budget.stop_at_limit),
                         ("haiku", "week", 1_000_000, None, True))
        self.assertContains(response, 'id="ai-budgets-panel"')
        self.assertIn("Weekly budget saved", response["HX-Trigger"])

    def test_editing_a_budget_changes_it(self):
        self._login("owner")
        self._save()
        budget = LLMBudget.objects.get()

        response = self._save(budget_id=str(budget.pk), input_limit="5", low_at_percent="25%")

        budget.refresh_from_db()
        self.assertEqual((budget.input_limit, budget.low_at_percent), (5, 25))
        self.assertIn("aiBudgetSaved", response["HX-Trigger"])  # the dialog closes

    def test_a_second_budget_for_the_same_model_and_period_is_refused(self):
        self._login("owner")
        self._save()

        response = self._save(input_limit="5")

        self.assertEqual(LLMBudget.objects.get().input_limit, 1_000_000)
        self.assertIn("already has a weekly budget", response["HX-Trigger"])
        self.assertNotIn("aiBudgetSaved", response["HX-Trigger"])  # the dialog stays open

    def test_a_budget_needs_a_limit(self):
        self._login("admin")

        response = self._save(input_limit="", output_limit="")

        self.assertFalse(LLMBudget.objects.exists())
        self.assertIn('"error"', response["HX-Trigger"])

    def test_a_member_cannot_set_or_remove_budgets_but_sees_them(self):
        budget = LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="day", input_limit=10)
        self._login("member")

        self._save()
        self.client.post(reverse("delete_ai_budget", args=[budget.pk]), **HTMX)
        page = self.client.get(reverse("tenant_settings"))

        self.assertEqual(list(LLMBudget.objects.values_list("period", flat=True)), ["day"])
        self.assertContains(page, "data-budget-table")
        self.assertNotContains(page, "Save budget")

    def test_an_admin_removes_a_budget(self):
        budget = LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="day", input_limit=10)
        self._login("admin")

        self.client.post(reverse("delete_ai_budget", args=[budget.pk]), **HTMX)

        self.assertFalse(LLMBudget.objects.exists())

    def test_another_workspaces_provider_is_refused(self):
        other = baker.make("app.LLMProvider", api_key="k")
        self._login("admin")

        self._save(model_key=f"{other.pk}|haiku")

        self.assertFalse(LLMBudget.objects.exists())


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class UnbudgetedRoleTests(TestCase):
    setUp = AIBudgetViewTests.setUp
    _login = AIBudgetViewTests._login

    def test_a_role_on_a_model_without_a_budget_is_flagged_with_a_way_to_add_one(self):
        self._login("admin")

        body = self.client.get(reverse("tenant_settings")).content.decode()

        self.assertIn('data-role-unbudgeted="reasoning"', body)
        self.assertIn("reasoning runs are blocked", body)

    def test_a_budget_clears_the_flag(self):
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="day", input_limit=10)
        self._login("admin")

        self.assertNotIn("data-role-unbudgeted", self.client.get(reverse("tenant_settings")).content.decode())

    def test_a_budgeted_model_is_always_offered_so_its_edit_finds_it(self):
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="retired-model", period="day", input_limit=10)
        self._login("admin")

        body = self.client.get(reverse("tenant_settings")).content.decode()

        self.assertIn(f'<option value="{self.provider.pk}|retired-model">', body)
