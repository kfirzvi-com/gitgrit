from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_service import ProjectService


class TestServerSideRemoteNormalization(APITestCase):
    """Phase 1.2 — non-plugin clients get the same hit rate as the plugin."""

    def setUp(self):
        self.service = ProjectService()
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make(
            "app.Project",
            tenant=self.tenant,
            full_path="acme/backend",
            web_url="https://github.com/acme/backend",
        )

    def _expect_hit(self, **kwargs):
        result = self.service.resolve_project(self.tenant, **kwargs)
        assert result.get("id") == str(self.project.id), (
            f"expected hit for {kwargs}, got {result}"
        )
        return result

    def test_ssh_form_resolves(self):
        self._expect_hit(web_url="git@github.com:acme/backend.git")

    def test_ssh_protocol_form_resolves(self):
        self._expect_hit(web_url="ssh://git@github.com/acme/backend.git")

    def test_trailing_dot_git_strips(self):
        self._expect_hit(web_url="https://github.com/acme/backend.git")

    def test_uppercase_host_normalises(self):
        self._expect_hit(web_url="https://GitHub.com/acme/backend")

    def test_credentials_strip(self):
        self._expect_hit(web_url="https://user:tok@github.com/acme/backend")

    def test_full_path_with_leading_slash(self):
        self._expect_hit(repo_full_path="/acme/backend")

    def test_full_path_with_dot_git_suffix(self):
        self._expect_hit(repo_full_path="acme/backend.git")
