"""A project's root path: where it starts inside its repository."""
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.domain.projects import InvalidRootPath, RootPath


class RootPathParseTests(SimpleTestCase):
    def test_normalises_slashes_and_dots(self):
        for raw in ("apps/web", "/apps/web/", "./apps/web", "apps//web", " apps\\web "):
            self.assertEqual(RootPath.parse(raw).value, "apps/web", raw)

    def test_empty_means_the_whole_repository(self):
        for raw in ("", None, "/", ".", "./"):
            self.assertTrue(RootPath.parse(raw).is_repository_root, raw)

    def test_rejects_paths_leaving_the_repository(self):
        for raw in ("../x", "apps/../../x", "C:/repo"):
            with self.assertRaises(InvalidRootPath, msg=raw):
                RootPath.parse(raw)


class RootPathCoversTests(SimpleTestCase):
    def test_repository_root_covers_every_change(self):
        self.assertTrue(RootPath("").covers(["services/api/main.py"]))
        self.assertTrue(RootPath("").covers([]))

    def test_a_directory_covers_only_changes_inside_it(self):
        web = RootPath("apps/web")
        self.assertTrue(web.covers(["README.md", "apps/web/src/index.ts"]))
        self.assertFalse(web.covers(["apps/web-admin/index.ts", "README.md"]))
        self.assertFalse(web.covers([]))

    def test_unknown_changes_cover_everything(self):
        self.assertTrue(RootPath("apps/web").covers(None))

    def test_translates_between_project_and_repository_paths(self):
        web = RootPath("apps/web")
        self.assertEqual(web.to_repository("package.json"), "apps/web/package.json")
        self.assertEqual(web.to_repository(""), "apps/web")
        self.assertEqual(web.to_project("apps/web/src/a.ts"), "src/a.ts")
        self.assertIsNone(web.to_project("apps/other/a.ts"))
        self.assertEqual(RootPath("").to_project("a/b"), "a/b")


class ProjectsInOneRepositoryTests(TestCase):
    def _project(self, conn, root_path):
        return baker.make(
            "app.Project", tenant=conn.tenant, platform_connection=conn,
            external_id="42", full_path="org/mono", root_path=root_path,
        )

    def test_one_repository_holds_projects_at_different_paths(self):
        conn = baker.make("app.PlatformConnection", platform="github")
        root = self._project(conn, "")
        web = self._project(conn, "apps/web")
        self.assertEqual(root.ref, "org/mono")
        self.assertEqual(web.ref, "org/mono#apps/web")
        self.assertEqual(web.repository_label, "org/mono / apps/web")

    def test_one_project_per_path(self):
        conn = baker.make("app.PlatformConnection", platform="github")
        self._project(conn, "apps/web")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._project(conn, "apps/web")
