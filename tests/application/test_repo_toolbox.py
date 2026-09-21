"""The repository tools handed to the dependency-map model.

These tests pin the tool *contract*: every way a model may name the root works,
a miss returns an actionable sentence rather than an empty list, large trees are
summarized instead of truncated mid-list, and the toolbox records what was read
so the caller can refuse an ungrounded answer.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.infrastructure.topology.snapshots import PlatformSnapshot
from app.infrastructure.topology.toolbox import MAX_LISTING_ENTRIES, RepoToolbox


def _RepoToolbox(client, full_path, ref, scope=""):
    return RepoToolbox(PlatformSnapshot(client, full_path, ref), full_path, scope)


def _client(tree, files=None):
    files = files or {}
    return SimpleNamespace(
        get_tree=lambda full_path, ref: list(tree),
        get_file_content=lambda full_path, path, ref: files.get(path),
    )


SMALL_TREE = [
    "README.md",
    "pyproject.toml",
    "app/main.py",
    "app/settings.py",
    "infra/terraform/main.tf",
    "node_modules/left-pad/index.js",
]


class ListRepoFilesTests(SimpleTestCase):
    def _toolbox(self, tree=SMALL_TREE, full_path="org/service"):
        return _RepoToolbox(_client(tree), full_path, "main")

    def test_every_root_spelling_lists_the_whole_repo(self):
        for root in ["", ".", "/", "./", "org/service", "service", "ORG/SERVICE", " . "]:
            out = self._toolbox().list_repo_files(root)
            self.assertIn("README.md", out, root)
            self.assertIn("infra/terraform/main.tf", out, root)

    def test_noise_directories_are_hidden(self):
        out = self._toolbox().list_repo_files("")
        self.assertNotIn("node_modules", out)

    def test_directory_prefix_lists_only_that_directory(self):
        out = self._toolbox().list_repo_files("app")
        self.assertEqual(out.splitlines(), ["app/main.py", "app/settings.py"])
        # Leading './' and trailing '/' are tolerated.
        self.assertEqual(self._toolbox().list_repo_files("./app/"), out)

    def test_missing_directory_returns_an_actionable_message_not_empty(self):
        out = self._toolbox().list_repo_files("src")
        self.assertTrue(out)
        self.assertIn("No files under 'src'", out)
        self.assertIn("Top-level entries", out)
        self.assertIn("app", out)
        self.assertIn("Pass ''", out)

    def test_empty_tree_is_reported_and_recorded(self):
        tb = self._toolbox(tree=[])
        out = tb.list_repo_files("")
        self.assertIn("listing is empty", out)
        self.assertEqual(tb.tree_size, 0)

    def test_tree_size_counts_before_noise_filtering(self):
        tb = self._toolbox()
        tb.list_repo_files("")
        self.assertEqual(tb.tree_size, len(SMALL_TREE))

    def test_large_tree_gets_a_summary_with_manifests(self):
        tree = [f"packages/pkg{i}/src/file{j}.ts" for i in range(20) for j in range(30)]
        tree += [f"packages/pkg{i}/package.json" for i in range(20)]
        tree += ["package.json", "README.md"]
        self.assertGreater(len(tree), MAX_LISTING_ENTRIES)

        out = self._toolbox(tree=tree).list_repo_files("")
        self.assertIn("Root files:", out)
        self.assertIn("package.json", out)
        self.assertIn("packages/ (", out)
        self.assertIn("packages/pkg7/package.json", out)
        self.assertIn("list_repo_files(path=", out)
        # The summary is bounded even though the tree is not.
        self.assertLess(len(out.splitlines()), MAX_LISTING_ENTRIES)

    def test_large_directory_listing_is_capped_with_a_hint(self):
        tree = [f"src/file{i}.py" for i in range(MAX_LISTING_ENTRIES + 25)]
        out = self._toolbox(tree=tree).list_repo_files("src")
        self.assertIn("25 more files under 'src'", out)


class ReadFileTests(SimpleTestCase):
    def test_reads_and_records_evidence(self):
        tb = _RepoToolbox(_client(SMALL_TREE, {"pyproject.toml": "[project]"}), "org/s", "main")
        self.assertEqual(tb.read_file("./pyproject.toml"), "[project]")
        self.assertEqual(tb.files_read, ["pyproject.toml"])

    def test_missing_or_binary_file_returns_a_sentinel_and_no_evidence(self):
        tb = _RepoToolbox(_client(SMALL_TREE), "org/s", "main")
        out = tb.read_file("Dockerfile")
        self.assertIn("no readable file at 'Dockerfile'", out)
        self.assertEqual(tb.files_read, [])

    def test_empty_file_counts_as_read(self):
        tb = _RepoToolbox(_client(SMALL_TREE, {"README.md": ""}), "org/s", "main")
        out = tb.read_file("README.md")
        self.assertIn("exists but is empty", out)
        self.assertEqual(tb.files_read, ["README.md"])


class ScopedToolboxTests(SimpleTestCase):
    """A component's toolbox lists its own directory by default but can still
    read repository-root files, and shares evidence with its parent."""

    TREE = [
        "README.md",
        "docker-compose.yml",
        "apps/api-gateway/package.json",
        "apps/api-gateway/src/index.ts",
        "services/auth-service/pyproject.toml",
    ]

    def test_root_spellings_list_the_scope_directory(self):
        tb = _RepoToolbox(_client(self.TREE), "org/mono", "main").scoped("apps/api-gateway")
        for spelling in ("", ".", "/", "apps/api-gateway"):
            out = tb.list_repo_files(spelling)
            self.assertIn("apps/api-gateway/package.json", out)
            self.assertNotIn("services/auth-service", out)

    def test_explicit_other_directory_still_works(self):
        tb = _RepoToolbox(_client(self.TREE), "org/mono", "main").scoped("apps/api-gateway")
        self.assertIn("pyproject.toml", tb.list_repo_files("services/auth-service"))

    def test_reads_root_files_and_scope_relative_paths(self):
        files = {"docker-compose.yml": "services:", "apps/api-gateway/package.json": "{}"}
        parent = _RepoToolbox(_client(self.TREE, files), "org/mono", "main")
        tb = parent.scoped("apps/api-gateway")
        tb.list_repo_files("")
        self.assertEqual(tb.read_file("docker-compose.yml"), "services:")
        self.assertEqual(tb.read_file("package.json"), "{}")  # resolved inside the scope
        # Evidence is shared with the parent, recorded with full paths.
        self.assertEqual(parent.files_read, ["docker-compose.yml", "apps/api-gateway/package.json"])
        self.assertEqual(parent.tree_size, len(self.TREE))
