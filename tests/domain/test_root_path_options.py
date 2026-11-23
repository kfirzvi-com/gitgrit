"""Picking a root path: the repository's directories, apps and services
(directories holding a build manifest) first."""
from django.test import SimpleTestCase

from app.domain.projects.root_path_options import RootPathOptions

FILES = [
    "README.md",
    "package.json",
    "apps/web/package.json",
    "apps/web/src/index.ts",
    "services/api/go.mod",
    "services/api/Dockerfile",
    "services/api/internal/handler.go",
    "apps/web/node_modules/react/package.json",
    ".github/workflows/ci.yml",
    "docs/guide.md",
]


class RootPathOptionsTests(SimpleTestCase):
    def test_apps_and_services_come_first_named_by_their_manifests(self):
        options = RootPathOptions(FILES).options()
        self.assertEqual(
            [(o.path, o.manifests) for o in options[:2]],
            [("apps/web", ("package.json",)), ("services/api", ("Dockerfile", "go.mod"))],
        )

    def test_every_other_directory_follows(self):
        paths = [o.path for o in RootPathOptions(FILES).options()]
        self.assertEqual(paths[2:], ["apps", "apps/web/src", "docs", "services", "services/api/internal"])

    def test_hidden_and_dependency_directories_are_left_out(self):
        paths = {o.path for o in RootPathOptions(FILES).options()}
        self.assertFalse(any(".github" in p or "node_modules" in p for p in paths))

    def test_paths_already_projects_are_left_out(self):
        paths = {o.path for o in RootPathOptions(FILES, taken=["apps/web", ""]).options()}
        self.assertNotIn("apps/web", paths)
        self.assertIn("services/api", paths)
