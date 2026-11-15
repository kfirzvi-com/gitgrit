"""The dashboard's reads and AI budgets over the public API: the overview,
AI usage, budgetable models, budgets (owners and admins write), and stacks."""
from unittest.mock import patch

from model_bakery import baker

from app.domain.models import APIToken, LLMBudget
from tests.api.test_public_api import PublicAPITestCase, make_oauth_token


def _project(tenant, **kw):
    connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    return baker.make("app.Project", tenant=tenant, platform_connection=connection, tags=[], languages=[], **kw)


class CockpitAPITestCase(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.provider = baker.make("app.LLMProvider", tenant=self.tenant, display_name="Anthropic", api_key="k",
                                   available_models=["haiku", "sonnet"])
        baker.make("app.LLMRole", tenant=self.tenant, provider=self.provider, name="reasoning", model="haiku")

    def as_role(self, role):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        self.auth = {"Authorization": f"Bearer {make_oauth_token(user)}"}
        return user

    def budget(self, **kw):
        fields = {"tenant": self.tenant, "provider": self.provider, "model": "haiku", "period": "month",
                  "input_limit": 1000, "output_limit": None, "stop_at_limit": False, "low_at_percent": None}
        return baker.make("app.LLMBudget", **{**fields, **kw})

    def spend(self, model="haiku", category="standard", **kw):
        return baker.make("app.LLMUsage", tenant=self.tenant, provider=self.provider, provider_name="Anthropic",
                          model=model, category=category, **kw)


class TestOverview(CockpitAPITestCase):
    def test_counts_lights_and_who_needs_you(self):
        project = _project(self.tenant, name="api", owner="platform")

        body = self.get(f"{self.ws}/overview/").json()

        assert body["health"] == {"total": 1, "failed": 0, "needs_attention": 1, "healthy": 0,
                                  "checked": 0, "unchecked": 1}
        assert [light["key"] for light in body["lights"]] == ["failed", "below_a", "no_score", "ai_budget"]
        assert next(light for light in body["lights"] if light["key"] == "no_score")["lit"]
        assert body["needs_you"] == [{
            "project": {"id": str(project.pk), "name": "api"}, "tone": "needs_attention", "grade": None,
            "why": "Not checked yet", "owner": "platform", "stacks": [],
        }]
        assert body["last_check"] is None
        assert body["checks"] == {"this_week": 0, "last_week": 0, "peak": 0}
        assert len(body["trend"]) == 5

    def test_the_ai_budget_light_turns_on_when_a_budget_runs_low(self):
        self.budget(low_at_percent=50)
        self.spend(input_tokens=600)

        light = next(x for x in self.get(f"{self.ws}/overview/").json()["lights"] if x["key"] == "ai_budget")

        assert (light["lit"], light["count"], light["tone"]) == (True, 1, "needs_attention")


class TestAIUsage(CockpitAPITestCase):
    def test_tokens_per_model_with_budgets_categories_and_standards(self):
        self.budget()
        self.spend(input_tokens=300, output_tokens=40, calls=2, standard_name="Docs")
        self.spend(model="sonnet", category="map", input_tokens=10, output_tokens=5, calls=1)

        body = self.get(f"{self.ws}/ai/usage/", period="week").json()

        assert body["period"] == "week"
        assert body["budgets"]["total"] == 1
        models = {m["model"]: m for m in body["providers"][0]["models"]}
        assert (models["haiku"]["input_tokens"], models["haiku"]["output_tokens"]) == (300, 40)
        assert models["haiku"]["blocked"] is False
        assert models["haiku"]["budgets"][0]["used"] == {"input_tokens": 300, "output_tokens": 40}
        assert models["sonnet"]["blocked"] is True
        assert {c["category"]: c["input_tokens"] for c in body["categories"]} == {"map": 10, "standard": 300}
        assert [(s["name"], s["share"]) for s in body["standards"]] == [("Docs", 1.0)]

    def test_an_unknown_period_is_400(self):
        assert self.get(f"{self.ws}/ai/usage/", period="year").status_code == 400


class TestAIModels(CockpitAPITestCase):
    def test_role_models_first_and_unbudgeted_ones_blocked(self):
        self.budget(model="sonnet")

        body = self.get(f"{self.ws}/ai/models/").json()

        assert [(m["model"], m["roles"], m["blocked"]) for m in body] == [
            ("haiku", ["Reasoning"], True), ("sonnet", [], False),
        ]
        assert body[0]["provider"] == {"id": str(self.provider.pk), "name": "Anthropic"}


class TestAIBudgets(CockpitAPITestCase):
    def test_an_admin_sets_changes_and_removes_a_budget(self):
        self.as_role("admin")

        created = self.send("post", f"{self.ws}/ai/budgets/", {
            "provider_id": str(self.provider.pk), "model": "haiku", "period": "week",
            "input_limit": 5000, "low_at_percent": 20, "stop_at_limit": True,
        })
        assert created.status_code == 201, created.content
        budget = created.json()
        assert (budget["model"], budget["period"], budget["input_limit"], budget["output_limit"]) == (
            "haiku", "week", 5000, None)
        assert (budget["low_at_percent"], budget["stop_at_limit"], budget["level"]) == (20, True, "ok")
        assert set(budget["window"]) == {"starts", "last_day", "resets"}

        changed = self.send("patch", f"{self.ws}/ai/budgets/{budget['id']}/", {"output_limit": 900})
        assert changed.status_code == 200
        assert (changed.json()["input_limit"], changed.json()["output_limit"]) == (5000, 900)

        assert self.send("delete", f"{self.ws}/ai/budgets/{budget['id']}/").status_code == 204
        assert not LLMBudget.objects.exists()

    def test_everyone_reads_budgets(self):
        self.budget()
        self.as_role("member")

        assert [b["model"] for b in self.get(f"{self.ws}/ai/budgets/").json()] == ["haiku"]

    def test_members_and_workspace_tokens_cannot_write(self):
        budget = self.budget()
        self.as_role("member")
        assert self.send("post", f"{self.ws}/ai/budgets/", {
            "provider_id": str(self.provider.pk), "model": "sonnet", "period": "day", "input_limit": 1,
        }).status_code == 403
        assert self.send("delete", f"{self.ws}/ai/budgets/{budget.pk}/").status_code == 403

        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.auth = {"Authorization": f"Bearer {raw}"}
        assert self.send("patch", f"{self.ws}/ai/budgets/{budget.pk}/", {"input_limit": 2}).status_code == 403

    def test_a_second_budget_for_the_same_model_and_period_is_400(self):
        self.budget(period="week")

        r = self.send("post", f"{self.ws}/ai/budgets/", {
            "provider_id": str(self.provider.pk), "model": "haiku", "period": "week", "input_limit": 1,
        })

        assert r.status_code == 400
        assert "already has a weekly budget" in r.json()["detail"]

    def test_a_budget_needs_a_limit(self):
        r = self.send("post", f"{self.ws}/ai/budgets/", {
            "provider_id": str(self.provider.pk), "model": "haiku", "period": "week",
        })
        assert r.status_code == 400

    def test_another_workspaces_budget_is_404(self):
        other = baker.make("app.LLMBudget", tenant=baker.make("app.Tenant"), model="x", period="day", input_limit=1)
        assert self.send("delete", f"{self.ws}/ai/budgets/{other.pk}/").status_code == 404


class TestStacks(CockpitAPITestCase):
    def setUp(self):
        super().setUp()
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Payments", description="Money")
        self.project = _project(self.tenant, name="ledger")
        self.project.root_component.stacks.add(self.stack)

    def test_list_counts_each_stacks_projects(self):
        body = self.get(f"{self.ws}/stacks/").json()

        assert body == [{"id": str(self.stack.pk), "name": "Payments", "description": "Money", "project_count": 1,
                         "failed": 0, "needs_attention": 1, "healthy": 0}]

    def test_view_lists_components_worst_first(self):
        body = self.get(f"{self.ws}/stacks/{self.stack.pk}/").json()

        assert body["name"] == "Payments"
        assert body["map_refreshing"] is False
        component = body["components"][0]
        assert (component["name"], component["project"]["name"], component["why"]) == (
            self.project.root_component.name, "ledger", "Not checked yet")

    def test_another_workspaces_stack_is_404(self):
        other = baker.make("app.Stack", tenant=baker.make("app.Tenant"))
        assert self.get(f"{self.ws}/stacks/{other.pk}/").status_code == 404

    def test_only_superusers_refresh_a_map(self):
        url = f"{self.ws}/stacks/{self.stack.pk}/refresh/"
        assert self.send("post", url).status_code == 403

        self.user.is_superuser = True
        self.user.save()
        with patch("app.application.dependency_agent._enqueue_refresh") as enqueue:
            r = self.send("post", url)

        assert r.status_code == 202
        assert r.json() == {"queued": 1}
        enqueue.assert_called_once_with(str(self.project.pk))
