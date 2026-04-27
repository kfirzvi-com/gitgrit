import asyncio
from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker
from mcp.server.fastmcp.prompts.base import UserMessage
from rest_framework.test import APITestCase

from app.infrastructure.mcp import context
from app.infrastructure.mcp.tools import policies, project_status, projects, reference, testing
from app.infrastructure.mcp.tools.policies import (
    create_policy,
    delete_policy,
    get_policy,
    list_policies,
    update_policy,
)
from app.infrastructure.mcp.tools.project_status import (
    get_active_policies_for_project,
    get_project_status,
    resolve_project,
    session_bootstrap,
)
from app.infrastructure.mcp.tools.projects import list_projects
from app.infrastructure.mcp.tools.prompts import audit_workspace, write_policy_from_requirement
from app.infrastructure.mcp.tools.reference import get_project_context_api
from app.infrastructure.mcp.tools.testing import run_policy_test


class _AuthedTestCase(APITestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        self._ctx_token = context.set_auth(
            context.AuthContext(user=self.user, tenant=self.tenant, client_kind="claude")
        )

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


class TestProjectStatusTools(_AuthedTestCase):
    def test_resolve_project_passes_tenant_and_args(self):
        with patch.object(
            project_status._project_service,
            "resolve_project",
            return_value={"id": "p1", "matched_by": "full_path"},
        ) as mock:
            result = asyncio.run(resolve_project(repo_full_path="acme/backend"))
        mock.assert_called_once_with(self.tenant, "acme/backend", None)
        assert result["id"] == "p1"

    def test_get_project_status_passes_tenant_and_id(self):
        with patch.object(
            project_status._status_service,
            "get_project_status",
            return_value={"grade": "good"},
        ) as mock:
            result = asyncio.run(get_project_status("abc"))
        mock.assert_called_once_with(self.tenant, "abc")
        assert result == {"grade": "good"}

    def test_get_active_policies_passes_tenant_and_id(self):
        sample = {
            "id": "p",
            "rules": {
                "watched_files": ["README.md"],
                "forbidden_patterns": [],
                "locally_enforceable": True,
                "watched_files_complete": True,
                "forbidden_patterns_complete": True,
            },
        }
        with patch.object(
            project_status._policy_service,
            "list_active_for_project",
            return_value=[sample],
        ) as mock:
            result = asyncio.run(get_active_policies_for_project("abc"))
        mock.assert_called_once_with(self.tenant, "abc")
        assert result[0]["rules"]["watched_files"] == ["README.md"]

    def test_session_bootstrap_fans_out_to_three_services(self):
        project = {"id": "p1", "name": "backend", "matched_by": "full_path"}
        status = {"grade": "good", "overall_score": 85}
        policies_list = [{"id": "pol1", "rules": {"watched_files": []}}]
        with (
            patch.object(
                project_status._project_service,
                "resolve_project",
                return_value=project,
            ) as resolve_mock,
            patch.object(
                project_status._status_service,
                "get_project_status",
                return_value=status,
            ) as status_mock,
            patch.object(
                project_status._policy_service,
                "list_active_for_project",
                return_value=policies_list,
            ) as policies_mock,
        ):
            result = asyncio.run(
                session_bootstrap(repo_full_path="acme/backend")
            )
        resolve_mock.assert_called_once_with(self.tenant, "acme/backend", None)
        status_mock.assert_called_once_with(self.tenant, "p1")
        policies_mock.assert_called_once_with(self.tenant, "p1")
        assert result == {"project": project, "status": status, "policies": policies_list}

    def test_session_bootstrap_match_no_policies(self):
        project = {"id": "p1", "name": "backend", "matched_by": "full_path"}
        status = {"grade": "unknown", "overall_score": None, "total_policies": 0}
        with (
            patch.object(
                project_status._project_service,
                "resolve_project",
                return_value=project,
            ),
            patch.object(
                project_status._status_service,
                "get_project_status",
                return_value=status,
            ),
            patch.object(
                project_status._policy_service,
                "list_active_for_project",
                return_value=[],
            ),
        ):
            result = asyncio.run(session_bootstrap(repo_full_path="acme/backend"))
        # Project resolved but zero applicable policies — wire shape still has all
        # three keys; policies is the empty list (not None).
        assert result == {"project": project, "status": status, "policies": []}

    def test_session_bootstrap_stable_shape_on_project_error(self):
        error_project = {"error": "no_match", "candidates": [{"full_path": "x/y"}]}
        with (
            patch.object(
                project_status._project_service,
                "resolve_project",
                return_value=error_project,
            ),
            patch.object(
                project_status._status_service, "get_project_status"
            ) as status_mock,
            patch.object(
                project_status._policy_service, "list_active_for_project"
            ) as policies_mock,
        ):
            result = asyncio.run(session_bootstrap(repo_full_path="x/y"))
        # On project error, status and policies are not called — and the result
        # still carries all three keys with null for the missing data.
        status_mock.assert_not_called()
        policies_mock.assert_not_called()
        assert result == {
            "project": error_project,
            "status": None,
            "policies": None,
        }


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
