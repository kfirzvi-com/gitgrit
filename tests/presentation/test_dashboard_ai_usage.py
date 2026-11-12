"""The dashboard's AI section: tokens by provider and model, by category and
by standard, for today, this week or this month."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import LLMBudget, LLMUsage

NON_MANIFEST_STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class DashboardAIUsageTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        baker.make("app.Project", tenant=self.tenant)
        self.provider = baker.make("app.LLMProvider", tenant=self.tenant, display_name="Anthropic", api_key="k")

    def _usage(self, model, i, o, category="standard", name=""):
        LLMUsage.objects.create(tenant=self.tenant, provider=self.provider, provider_name="Anthropic", model=model,
                                category=category, input_tokens=i, output_tokens=o, calls=1, standard_name=name)

    def test_shows_each_model_with_input_and_output_and_its_budget(self):
        self._usage("haiku", 12_000, 900)
        self._usage("sonnet", 3_000, 100, category="map")
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="month", input_limit=10_000)

        body = self.client.get(reverse("dashboard")).content.decode()
        section = body.split("data-ai-usage", 1)[1]

        self.assertIn('data-ai-model="haiku"', section)
        self.assertIn("12k", section)
        self.assertIn('data-budget-level="reached"', section)
        self.assertIn("1</b> used up", section)  # the header counts budgets, not tokens
        self.assertIn('data-ai-category="map"', section)
        self.assertNotIn("Set budgets", section)  # members only see them

    def test_flags_a_standard_that_spends_far_more_than_the_others(self):
        for name, total in (("Docs", 100), ("Lint", 120), ("CI", 110), ("Review", 900)):
            self._usage("haiku", total, 0, name=name)

        section = self.client.get(reverse("dashboard")).content.decode().split("data-ai-standards", 1)[1]

        self.assertEqual(section.count("data-heavy"), 1)
        self.assertIn("7.8&times; median", section)

    def test_the_period_switch_answers_with_the_section(self):
        response = self.client.get(reverse("dashboard_ai_usage") + "?period=week")

        self.assertContains(response, 'data-period="week"')
        self.assertContains(response, "No budgets set.")

    def test_no_models_set_up_says_so(self):
        self.provider.delete()

        self.assertContains(self.client.get(reverse("dashboard")), "No AI models set up yet.")

    def test_a_model_without_a_budget_shows_as_blocked(self):
        baker.make("app.LLMRole", tenant=self.tenant, provider=self.provider, name="reasoning", model="opus")
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="month", input_limit=10)

        body = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn("1 model blocked: no budget", body)
        model_row = body.split('data-ai-model="opus"', 1)[1].split("data-ai-model", 1)[0]
        self.assertIn("No budget &middot; blocked", model_row)

    def test_the_low_fuel_lamp_lights_when_a_budget_runs_low_and_the_tank_shows_its_mark(self):
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="month",
                                 input_limit=10_000, low_at_percent=25)
        self._usage("haiku", 8_000, 0)  # 20% left: under the 25% mark

        body = self.client.get(reverse("dashboard")).content.decode()

        lamp = body.split('data-light="ai_budget"', 1)[1][:400]
        self.assertTrue(body.split('data-light="ai_budget"', 1)[1].startswith(" data-lit"))
        self.assertIn("1 low", lamp)
        self.assertIn('style="bottom: 25%"', body)

    def test_the_low_fuel_lamp_is_dark_while_every_budget_is_above_its_mark(self):
        LLMBudget.objects.create(tenant=self.tenant, provider=self.provider, model="haiku", period="month",
                                 input_limit=10_000, low_at_percent=25)
        self._usage("haiku", 1_000, 0)

        body = self.client.get(reverse("dashboard")).content.decode()

        self.assertFalse(body.split('data-light="ai_budget"', 1)[1].startswith(" data-lit"))
