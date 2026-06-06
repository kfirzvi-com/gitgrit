"""View tests for the policy execution detail page."""
import pytest
from django.test import TestCase, override_settings
from model_bakery import baker

# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestPolicyExecutionDetailView(TestCase):
    def _login(self, role="admin"):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role=role)
        self.client.force_login(user)
        return user, tenant

    def _execution(self, tenant, **kw):
        project = baker.make("app.Project", tenant=tenant)
        defaults = dict(
            project=project,
            policy_name="Documentation Quality (LLM)",
            status="failed",
            score=0,
            message="The docs have significant gaps.",
            details={
                "violations": ["No setup instructions"],
                "llm_usage": {"total_tokens": 123, "calls": 4},
            },
            logs=[
                {"level": "info", "message": "tool: list_files() → 5 items", "t_ms": 12},
                {"level": "info", "message": "llm.reasoning: verdict passed=False", "t_ms": 800},
            ],
        )
        defaults.update(kw)
        return baker.make("app.PolicyExecution", **defaults)

    def test_anonymous_redirects(self):
        tenant = baker.make("app.Tenant")
        ex = self._execution(tenant)
        resp = self.client.get(f"/executions/{ex.id}/")
        assert resp.status_code == 302

    def test_renders_message_violations_usage_and_log(self):
        _, tenant = self._login()
        ex = self._execution(tenant)
        resp = self.client.get(f"/executions/{ex.id}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "The docs have significant gaps." in body
        assert "No setup instructions" in body
        assert "123" in body  # llm token total
        assert "tool: list_files() → 5 items" in body

    def test_other_tenant_execution_is_404(self):
        self._login()
        other_tenant = baker.make("app.Tenant")
        ex = self._execution(other_tenant)
        resp = self.client.get(f"/executions/{ex.id}/")
        assert resp.status_code == 404
