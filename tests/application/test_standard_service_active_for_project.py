import pytest
from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.standard_service import StandardService
from app.domain.models import StandardExecution


class TestListActiveForProject(APITestCase):
    def setUp(self):
        self.service = StandardService()
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make(
            "app.Project", tenant=self.tenant, languages=["Python"]
        )

    def test_excludes_disabled_and_draft_standards(self):
        baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=False, criteria={}
        )
        baker.make(
            "app.Standard", tenant=self.tenant, enabled=False, draft=False, criteria={}
        )
        baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=True, criteria={}
        )

        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        assert len(result) == 1

    def test_filters_by_language_match(self):
        baker.make(
            "app.Standard",
            tenant=self.tenant,
            enabled=True,
            draft=False,
            criteria={"languages": ["Python"]},
        )
        baker.make(
            "app.Standard",
            tenant=self.tenant,
            enabled=True,
            draft=False,
            criteria={"languages": ["Rust"]},
        )
        baker.make(
            "app.Standard",
            tenant=self.tenant,
            enabled=True,
            draft=False,
            criteria={"languages": []},  # language-agnostic
        )

        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        # Python match + language-agnostic. Rust is filtered out.
        assert len(result) == 2

    def test_ships_extracted_rules_not_raw_code(self):
        code = """
def evaluate(project):
    c = project.get_file_content("README.md") or ""
    return {"passed": "FIXME" not in c, "score": 100, "message": "", "details": {}}
"""
        baker.make(
            "app.Standard",
            tenant=self.tenant,
            enabled=True,
            draft=False,
            code=code,
            criteria={},
        )
        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        assert len(result) == 1
        standard = result[0]
        assert "code" not in standard
        rules = standard["rules"]
        assert rules["watched_files"] == ["README.md"]
        assert rules["forbidden_patterns"] == [{"kind": "in", "value": "FIXME"}]
        assert rules["locally_enforceable"] is True
        assert rules["watched_files_complete"] is True
        assert rules["forbidden_patterns_complete"] is True

    def test_includes_last_execution_for_project(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=False, criteria={}
        )
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            score=42,
            message="almost",
            status=StandardExecution.Status.FAILED,
        )

        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        assert result[0]["last_execution"]["score"] == 42
        assert result[0]["last_execution"]["message"] == "almost"

    def test_last_execution_is_null_when_never_run(self):
        baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=False, criteria={}
        )
        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        assert result[0]["last_execution"] is None

    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.list_active_for_project(
                self.tenant, "00000000-0000-0000-0000-000000000000"
            )

    def test_malformed_uuid_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.list_active_for_project(self.tenant, "not-a-uuid")

    def test_returns_empty_when_no_active_standards(self):
        # Project exists but tenant has no enabled, non-draft standards.
        result = self.service.list_active_for_project(self.tenant, str(self.project.id))
        assert result == []
