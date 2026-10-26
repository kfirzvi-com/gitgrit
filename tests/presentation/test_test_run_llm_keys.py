"""The standard editor's and the API's test runs hand the workspace's LLM keys
only to admins: the sandbox has network access, so a member's code could send
them out. Real runs of saved standards are not covered (see SECURITY.md)."""
import json
import secrets
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from oauth2_provider.models import AccessToken, Application, set_token_value

from app.application.project_service import (
    LLM_ADMIN_ONLY_MESSAGE,
    SandboxService,
    _evaluate_takes_llm,
)
from app.domain.models import APIToken, LLMProvider, LLMRole
from app.workspace_access import ACTIVE_TENANT_KEY, SUPPORT_VIEW_STARTED_KEY

RUNNER = "app.application.project_service.SandboxRunner"
PLAIN = 'def evaluate(project):\n    return {"passed": True, "score": 100, "message": "ok", "details": {}}\n'
NEEDS_LLM = (
    'def evaluate(project, llm):\n'
    '    return {"passed": True, "score": 100, "message": "ok", "details": {}}\n'
)
KEY = "sk-secret-key"


class TestTestRunLLMKeys(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        provider = LLMProvider.objects.create(
            tenant=self.tenant, display_name="p", provider_type="openai", api_key=KEY
        )
        LLMRole.objects.create(tenant=self.tenant, name="reasoning", provider=provider, model="gpt-x")
        self.admin = self._member("admin")
        self.member = self._member("member")

    def _member(self, role):
        user = baker.make("app.User", username=role, email=f"{role}@example.com")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        return user

    def _web(self, user, code, support_view=False):
        client = Client(headers={"host": "localhost"})
        client.force_login(user)
        session = client.session
        session[ACTIVE_TENANT_KEY] = str(self.tenant.id)
        if support_view:
            session[SUPPORT_VIEW_STARTED_KEY] = timezone.now().isoformat()
        session.save()
        with patch(RUNNER) as runner:
            runner.return_value.run.return_value = {"passed": True}
            r = client.post(
                reverse("run_standard_test"),
                json.dumps({"code": code, "input": {}}),
                content_type="application/json",
            )
        return r, runner

    def _oauth_token(self, user):
        raw = secrets.token_urlsafe(30)
        token = AccessToken(
            user=user,
            application=Application.objects.get(client_id="gitgrit-cli"),
            scope="read write",
            expires=timezone.now() + timedelta(hours=1),
        )
        set_token_value(token, raw)
        token.save()
        return raw

    def _api(self, user, code, raw=None):
        raw = raw or self._oauth_token(user)
        with patch(RUNNER) as runner:
            runner.return_value.run.return_value = {"passed": True}
            r = Client(headers={"host": "localhost"}).post(
                f"/api/v1/workspaces/{self.tenant.id}/standards/test/",
                json.dumps({"code": code, "mock_input": {}}),
                content_type="application/json",
                headers={"Authorization": f"Bearer {raw}"},
            )
        return r, runner

    @staticmethod
    def _input(runner):
        return runner.return_value.run.call_args.args[1]

    def test_admin_web_run_gets_role_keys(self):
        r, runner = self._web(self.admin, PLAIN)
        assert r.status_code == 200
        assert self._input(runner)["llm_roles"]["reasoning"]["api_key"] == KEY

    def test_member_web_run_gets_no_roles(self):
        r, runner = self._web(self.member, PLAIN)
        assert r.status_code == 200
        assert "llm_roles" not in self._input(runner)

    def test_member_running_an_llm_standard_is_told_why(self):
        r, runner = self._web(self.member, NEEDS_LLM)
        assert r.json()["message"] == LLM_ADMIN_ONLY_MESSAGE
        assert r.json()["passed"] is False
        runner.return_value.run.assert_not_called()

    def test_admin_api_run_gets_role_keys(self):
        r, runner = self._api(self.admin, PLAIN)
        assert r.status_code == 200
        assert self._input(runner)["llm_roles"]["reasoning"]["api_key"] == KEY

    def test_member_api_run_gets_no_roles(self):
        r, runner = self._api(self.member, PLAIN)
        assert r.status_code == 200
        assert "llm_roles" not in self._input(runner)

    def test_workspace_token_api_run_gets_no_roles(self):
        # Created by an admin, but a workspace token has no person behind it.
        _, raw = APIToken.issue(name="ci", created_by=self.admin, tenant=self.tenant)
        assert raw.startswith("grit_ws_")
        r, runner = self._api(None, PLAIN, raw=raw)
        assert r.status_code == 200
        assert "llm_roles" not in self._input(runner)

    def test_superuser_in_support_view_gets_no_roles(self):
        staff = baker.make("app.User", username="staff", is_superuser=True, is_staff=True)
        r, runner = self._web(staff, PLAIN, support_view=True)
        assert r.status_code == 200
        assert "llm_roles" not in self._input(runner)

    def test_admin_without_a_workspace_is_not_told_admins_only(self):
        with patch(RUNNER) as runner:
            runner.return_value.run.return_value = {"passed": True}
            result = SandboxService().run_standard_test(NEEDS_LLM, {}, tenant=None, include_llm=True)
        assert result == {"passed": True}  # the sandbox ran; no admins-only message
        runner.return_value.run.assert_called_once()


class TestEvaluateTakesLLMHostOnly(SimpleTestCase):
    """Signature cases run on both sides in tests/test_sandbox_parity.py; code
    the sandbox could not even exec stays host-only."""

    def test_unparsable_code_does_not_take_llm(self):
        assert _evaluate_takes_llm("def evaluate(") is False
