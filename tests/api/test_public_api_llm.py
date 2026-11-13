"""LLM providers and roles over the public API: owners and admins change
them, members read them, and a key never comes back out."""
from unittest.mock import patch

from model_bakery import baker

from app.domain.models import APIToken, LLMProvider, LLMRole
from app.infrastructure.llm_models import Discovery, ProbeResult
from tests.api.test_public_api import PublicAPITestCase, make_oauth_token

DISCOVER = "app.application.llm_providers.llm_provider_service.discover"
TEST = "app.application.llm_providers.llm_provider_service.test_provider"


def _found(models, reason=""):
    """What discovery found; a reason comes from the models the key was refused."""
    refused = [ProbeResult(model="haiku", verdict=False, detail=reason)] if reason else []
    return Discovery(models=models, results=refused)


class LLMAPITestCase(PublicAPITestCase):
    def as_role(self, role):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        self.auth = {"Authorization": f"Bearer {make_oauth_token(user)}"}

    def provider(self, **kw):
        fields = {"tenant": self.tenant, "provider_type": "anthropic", "display_name": "Anthropic",
                  "api_key": "sk-secret", "available_models": ["haiku", "sonnet"]}
        return baker.make("app.LLMProvider", **{**fields, **kw})


class TestProviders(LLMAPITestCase):
    def test_add_finds_the_models_and_never_returns_the_key(self):
        with patch(DISCOVER, return_value=_found(["haiku", "sonnet"])) as discover:
            r = self.send("post", f"{self.ws}/llm/providers/", {"provider_type": "anthropic", "api_key": "sk-secret"})

        assert r.status_code == 201, r.content
        body = r.json()
        assert (body["display_name"], body["models"], body["note"]) == ("Anthropic", ["haiku", "sonnet"], "")
        assert "sk-secret" not in r.content.decode()
        discover.assert_called_once_with("anthropic", "", "sk-secret")
        assert LLMProvider.objects.get().api_key == "sk-secret"

    def test_add_says_why_no_model_was_found(self):
        self.provider()
        with patch(DISCOVER, return_value=_found([], "Your credits are depleted")):
            body = self.send("post", f"{self.ws}/llm/providers/", {"provider_type": "anthropic", "api_key": "k"}).json()

        assert (body["display_name"], body["models"], body["note"]) == ("Anthropic 2", [], "Your credits are depleted")

    def test_an_unknown_type_is_400(self):
        r = self.send("post", f"{self.ws}/llm/providers/", {"provider_type": "skynet", "api_key": "k"})
        assert r.status_code == 400

    def test_list_names_the_roles_using_each(self):
        p = self.provider()
        baker.make("app.LLMRole", tenant=self.tenant, provider=p, name="code", model="haiku")
        self.as_role("member")

        body = self.get(f"{self.ws}/llm/providers/").json()

        assert [(x["display_name"], x["roles"]) for x in body] == [("Anthropic", ["code"])]
        assert "sk-secret" not in str(body)

    def test_edit_changes_only_what_is_sent(self):
        p = self.provider(base_url="https://proxy.example.com")

        r = self.send("patch", f"{self.ws}/llm/providers/{p.pk}/", {"display_name": "Claude", "models": ["opus"]})

        assert r.status_code == 200
        p.refresh_from_db()
        assert (p.display_name, p.available_models, p.base_url, p.api_key) == (
            "Claude", ["opus"], "https://proxy.example.com", "sk-secret")

    def test_remove_clears_its_roles(self):
        p = self.provider()
        baker.make("app.LLMRole", tenant=self.tenant, provider=p, name="code", model="haiku")

        assert self.send("delete", f"{self.ws}/llm/providers/{p.pk}/").status_code == 204
        assert not LLMProvider.objects.exists() and not LLMRole.objects.exists()

    def test_test_and_refresh_models(self):
        p = self.provider()
        with patch(TEST, return_value=True):
            assert self.send("post", f"{self.ws}/llm/providers/{p.pk}/test/").json() == {"ok": True}
        with patch(DISCOVER, return_value=_found(["opus"])):
            assert self.send("post", f"{self.ws}/llm/providers/{p.pk}/models/refresh/").json() == {
                "models": ["opus"], "note": ""}
        p.refresh_from_db()
        assert p.available_models == ["opus"]

    def test_members_and_workspace_tokens_cannot_change_providers(self):
        p = self.provider()
        self.as_role("member")
        assert self.send("post", f"{self.ws}/llm/providers/", {"provider_type": "openai", "api_key": "k"}).status_code == 403
        assert self.send("delete", f"{self.ws}/llm/providers/{p.pk}/").status_code == 403

        _, raw = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.auth = {"Authorization": f"Bearer {raw}"}
        assert self.send("patch", f"{self.ws}/llm/providers/{p.pk}/", {"display_name": "x"}).status_code == 403

    def test_another_workspaces_provider_is_404(self):
        other = baker.make("app.LLMProvider", tenant=baker.make("app.Tenant"), provider_type="openai", api_key="k")
        assert self.send("delete", f"{self.ws}/llm/providers/{other.pk}/").status_code == 404


class TestRoles(LLMAPITestCase):
    def test_list_has_every_role_set_or_not(self):
        p = self.provider()
        baker.make("app.LLMRole", tenant=self.tenant, provider=p, name="reasoning", model="haiku")
        baker.make("app.LLMBudget", tenant=self.tenant, provider=p, model="haiku", period="month", input_limit=1)

        body = self.get(f"{self.ws}/llm/roles/").json()

        assert body == [
            {"role": "reasoning", "label": "Reasoning", "provider": {"id": str(p.pk), "name": "Anthropic"},
             "model": "haiku", "has_budget": True},
            {"role": "code", "label": "Code", "provider": None, "model": None, "has_budget": False},
        ]

    def test_set_and_clear_a_role(self):
        p = self.provider()

        r = self.send("put", f"{self.ws}/llm/roles/code/", {"provider_id": str(p.pk), "model": "sonnet"})
        assert r.status_code == 200
        assert (r.json()["model"], r.json()["has_budget"]) == ("sonnet", False)
        assert LLMRole.objects.get(name="code").model == "sonnet"

        assert self.send("delete", f"{self.ws}/llm/roles/code/").status_code == 204
        assert not LLMRole.objects.exists()

    def test_an_unknown_role_is_400_and_a_foreign_provider_404(self):
        p = self.provider()
        assert self.send("put", f"{self.ws}/llm/roles/poetry/", {"provider_id": str(p.pk), "model": "x"}).status_code == 400
        other = baker.make("app.LLMProvider", tenant=baker.make("app.Tenant"), provider_type="openai", api_key="k")
        assert self.send("put", f"{self.ws}/llm/roles/code/", {"provider_id": str(other.pk), "model": "x"}).status_code == 404

    def test_members_cannot_set_roles(self):
        p = self.provider()
        self.as_role("member")
        assert self.send("put", f"{self.ws}/llm/roles/code/", {"provider_id": str(p.pk), "model": "x"}).status_code == 403
