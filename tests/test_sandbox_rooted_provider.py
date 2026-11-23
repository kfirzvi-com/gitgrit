"""A project inside a monorepo: the sandbox reads it from its own directory,
and a standard can still reach the whole repository on purpose."""
import sys
from pathlib import Path

from django.test import SimpleTestCase

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from project_context import ProjectContext  # noqa: E402
from providers import languages as sandbox_languages  # noqa: E402
from providers.factory import create_project_provider  # noqa: E402

from app.domain.projects import languages as domain_languages  # noqa: E402

DATA = {
    "list_files": ["pnpm-lock.yaml", "CODEOWNERS", "apps/web/package.json", "apps/web/src/a.ts", "apps/webx/y.ts"],
    "get_file_content": {"apps/web/package.json": "{}", "pnpm-lock.yaml": "lock"},
}


def _context(root_path):
    provider, repository = create_project_provider(
        root_path=root_path, platform="mock", project_id="p", access_token=None, mock_data=DATA
    )
    return ProjectContext(provider, repository=repository)


class RootedProjectContextTests(SimpleTestCase):
    def test_files_are_listed_and_read_from_the_project_root(self):
        project = _context("apps/web")
        self.assertEqual(project.list_files(), ["package.json", "src/a.ts"])
        self.assertEqual(project.get_file_content("package.json"), "{}")
        self.assertIsNone(project.get_file_content("pnpm-lock.yaml"))

    def test_the_whole_repository_stays_reachable(self):
        project = _context("apps/web")
        self.assertEqual(project.get_repository_file_content("pnpm-lock.yaml"), "lock")
        self.assertIn("CODEOWNERS", project.list_repository_files())

    def test_languages_are_counted_from_the_project_files(self):
        self.assertEqual(_context("apps/web").get_languages(), {"TypeScript": 100.0})

    def test_a_whole_repository_project_is_unchanged(self):
        project = _context("")
        self.assertEqual(project.list_files(), DATA["list_files"])
        self.assertEqual(project.list_repository_files(), DATA["list_files"])

    def test_sandbox_and_app_name_languages_alike(self):
        self.assertEqual(sandbox_languages._BY_EXTENSION, domain_languages._BY_EXTENSION)
        self.assertEqual(sandbox_languages._BY_NAME, domain_languages._BY_NAME)
