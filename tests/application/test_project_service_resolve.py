from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_service import RESOLVE_ERROR_NO_MATCH, ProjectService


class TestResolveProject(APITestCase):
    def setUp(self):
        self.service = ProjectService()
        self.tenant = baker.make("app.Tenant")

    def test_full_path_hit_returns_project_with_matched_by(self):
        project = baker.make(
            "app.Project", tenant=self.tenant, full_path="acme/backend"
        )
        result = self.service.resolve_project(self.tenant, repo_full_path="acme/backend")
        assert result["id"] == str(project.id)
        assert result["matched_by"] == "full_path"

    def test_web_url_fallback_when_full_path_misses(self):
        project = baker.make(
            "app.Project",
            tenant=self.tenant,
            full_path="acme/backend",
            web_url="https://github.com/acme/backend",
        )
        result = self.service.resolve_project(
            self.tenant,
            repo_full_path="different/path",
            web_url="https://github.com/acme/backend",
        )
        assert result["id"] == str(project.id)
        assert result["matched_by"] == "web_url"

    def test_credentials_are_stripped_before_web_url_lookup(self):
        # Stored web_url has no credentials — if stripping didn't happen, the
        # lookup would miss and we'd fall through to no_match.
        project = baker.make(
            "app.Project",
            tenant=self.tenant,
            full_path="acme/backend",
            web_url="https://github.com/acme/backend",
        )
        result = self.service.resolve_project(
            self.tenant,
            web_url="https://oauth2:TOKEN@github.com/acme/backend",
        )
        assert result.get("id") == str(project.id)

    def test_miss_returns_candidates_sorted_by_similarity(self):
        baker.make("app.Project", tenant=self.tenant, full_path="acme/backend")
        baker.make("app.Project", tenant=self.tenant, full_path="acme/frontend")
        baker.make("app.Project", tenant=self.tenant, full_path="other/repo")

        result = self.service.resolve_project(
            self.tenant, repo_full_path="acme/backned"  # typo
        )
        assert result["error"] == RESOLVE_ERROR_NO_MATCH
        assert "acme/backend" in result["candidates"]

    def test_miss_with_no_projects_returns_empty_candidates(self):
        result = self.service.resolve_project(
            self.tenant, repo_full_path="anything"
        )
        assert result == {"error": RESOLVE_ERROR_NO_MATCH, "candidates": []}

    def test_respects_tenant_boundary(self):
        other_tenant = baker.make("app.Tenant")
        baker.make(
            "app.Project", tenant=other_tenant, full_path="acme/backend"
        )
        result = self.service.resolve_project(
            self.tenant, repo_full_path="acme/backend"
        )
        assert result["error"] == RESOLVE_ERROR_NO_MATCH
