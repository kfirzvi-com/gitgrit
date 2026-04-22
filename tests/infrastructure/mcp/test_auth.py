import pytest
from model_bakery import baker
from rest_framework.test import APITestCase

from app.domain.models import APIToken
from app.infrastructure.mcp.auth import MCPBearerAuth


class TestMCPBearerAuth(APITestCase):
    def _make_token(self, user=None, tenant=None):
        user = user or baker.make("app.User")
        tenant = tenant or baker.make("app.Tenant")
        instance, raw_token = APIToken.generate()
        instance.user = user
        instance.tenant = tenant
        instance.name = "test"
        instance.save()
        return instance, raw_token, user, tenant

    def test_valid_token_returns_correct_user_and_tenant(self):
        instance, raw_token, user, tenant = self._make_token()
        ctx = MCPBearerAuth().resolve(raw_token)
        assert ctx.user == user
        assert ctx.tenant == tenant

    def test_valid_token_updates_last_used_at(self):
        instance, raw_token, _, _ = self._make_token()
        assert instance.last_used_at is None
        MCPBearerAuth().resolve(raw_token)
        instance.refresh_from_db()
        assert instance.last_used_at is not None

    def test_unknown_token_raises_permission_error(self):
        with pytest.raises(PermissionError):
            MCPBearerAuth().resolve("grit_doesnotexist")

    def test_wrong_raw_value_raises_permission_error(self):
        instance, raw_token, _, _ = self._make_token()
        with pytest.raises(PermissionError):
            MCPBearerAuth().resolve("grit_wrongvalue")

    def test_resolve_issues_two_queries(self):
        instance, raw_token, _, _ = self._make_token()
        with self.assertNumQueries(2):
            MCPBearerAuth().resolve(raw_token)
