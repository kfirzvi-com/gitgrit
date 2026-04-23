import asyncio
from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker
from mcp.server.fastmcp.prompts.base import UserMessage
from rest_framework.test import APITestCase

from app.infrastructure.mcp import context
from app.infrastructure.mcp.tools import policies, projects, reference, testing
from app.infrastructure.mcp.tools.policies import (
    create_policy,
    delete_policy,
    get_policy,
    list_policies,
    update_policy,
)
from app.infrastructure.mcp.tools.projects import list_projects
from app.infrastructure.mcp.tools.prompts import audit_workspace, write_policy_from_requirement
from app.infrastructure.mcp.tools.reference import get_project_context_api
from app.infrastructure.mcp.tools.testing import run_policy_test


class _AuthedTestCase(APITestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        self._ctx_token = context.set_auth(self.user, self.tenant)

    def tearDown(self):
        context.reset_auth(self._ctx_token)


class TestPolicyTools(_AuthedTestCase):
    def test_list_policies_passes_tenant(self):
        with patch.object(policies._service, "list_policies", return_value=[{"id": "1"}]) as mock:
            result = asyncio.run(list_policies())
        mock.assert_called_once_with(self.tenant)
        assert result == [{"id": "1"}]

    def test_get_policy_passes_tenant_and_id(self):
        with patch.object(policies._service, "get_policy", return_value={"id": "abc"}) as mock:
            result = asyncio.run(get_policy("abc"))
        mock.assert_called_once_with(self.tenant, "abc")
        assert result == {"id": "abc"}

    def test_create_policy_passes_user_tenant_and_data(self):
        with patch.object(policies._service, "create_policy", return_value={"id": "new"}) as mock:
            result = asyncio.run(create_policy(name="P", code="def evaluate(p): ..."))
        args = mock.call_args
        assert args[0][0] == self.tenant
        assert args[0][1] == self.user
        data = args[0][2]
        assert data["name"] == "P"
        assert data["code"] == "def evaluate(p): ..."
        assert result == {"id": "new"}

    def test_create_policy_defaults_events_and_labels_to_empty_lists(self):
        with patch.object(policies._service, "create_policy", return_value={}) as mock:
            asyncio.run(create_policy(name="P", code="..."))
        data = mock.call_args[0][2]
        assert data["events"] == []
        assert data["labels"] == []
        assert data["languages"] == []

    def test_update_policy_only_sends_non_none_fields(self):
        with patch.object(policies._service, "update_policy", return_value={}) as mock:
            asyncio.run(update_policy("abc", name="NewName"))
        data = mock.call_args[0][3]
        assert "name" in data
        assert data["name"] == "NewName"
        assert "code" not in data
        assert "description" not in data

    def test_update_policy_always_includes_change_summary(self):
        with patch.object(policies._service, "update_policy", return_value={}) as mock:
            asyncio.run(update_policy("abc", name="X"))
        data = mock.call_args[0][3]
        assert "change_summary" in data

    def test_delete_policy_returns_confirmed_dict(self):
        with patch.object(policies._service, "delete_policy", return_value=None):
            result = asyncio.run(delete_policy("abc"))
        assert result == {"deleted": True, "policy_id": "abc"}


class TestProjectTools(_AuthedTestCase):
    def test_list_projects_passes_tenant(self):
        with patch.object(projects._service, "list_projects", return_value=[{"id": "p1"}]) as mock:
            result = asyncio.run(list_projects())
        mock.assert_called_once_with(self.tenant)
        assert result == [{"id": "p1"}]


class TestReferenceTools(_AuthedTestCase):
    def test_get_project_context_api_returns_service_value(self):
        with patch.object(reference._service, "get_project_context_api", return_value="API docs") as mock:
            result = get_project_context_api()
        mock.assert_called_once()
        assert result == "API docs"


class TestTestingTools(APITestCase):
    def test_run_policy_test_calls_sandbox(self):
        mock_input = {"files": []}
        with patch.object(testing._service, "run_policy_test", return_value={"passed": True}) as mock:
            result = run_policy_test("def evaluate(p): ...", mock_input)
        mock.assert_called_once_with("def evaluate(p): ...", mock_input)
        assert result == {"passed": True}

    def test_run_policy_test_defaults_mock_input_to_empty_dict(self):
        with patch.object(testing._service, "run_policy_test", return_value={}) as mock:
            run_policy_test("code")
        mock.assert_called_once_with("code", {})

    def test_run_policy_test_works_without_auth_context(self):
        with patch.object(testing._service, "run_policy_test", return_value={"passed": False}):
            result = run_policy_test("code")
        assert result == {"passed": False}


class TestPromptTools:
    def test_write_policy_prompt_returns_one_user_message(self):
        result = write_policy_from_requirement(requirement="every repo must have a README")
        assert len(result) == 1
        assert isinstance(result[0], UserMessage)

    def test_write_policy_prompt_contains_requirement_text(self):
        result = write_policy_from_requirement(requirement="every repo must have a README")
        assert "README" in result[0].content.text

    def test_write_policy_prompt_with_language_includes_language(self):
        result = write_policy_from_requirement(requirement="check CI", language="python")
        assert "python" in result[0].content.text

    def test_write_policy_prompt_without_language_omits_language_step(self):
        result = write_policy_from_requirement(requirement="check CI")
        assert "languages=" not in result[0].content.text

    def test_audit_workspace_returns_one_user_message(self):
        result = audit_workspace()
        assert len(result) == 1
        assert isinstance(result[0], UserMessage)

    def test_audit_workspace_contains_all_four_steps(self):
        result = audit_workspace()
        text = result[0].content.text
        assert "Step 1" in text
        assert "Step 2" in text
        assert "Step 3" in text
        assert "Step 4" in text
