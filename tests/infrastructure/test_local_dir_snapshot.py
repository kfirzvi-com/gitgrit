"""``LocalDirSnapshot``: a checkout on disk as a ``RepositorySnapshot``."""
from django.test import SimpleTestCase

from app.infrastructure.topology.snapshots import LocalDirSnapshot
from tests.support import TmpPathMixin


class LocalDirSnapshotTests(TmpPathMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        (self.tmp_path / ".git").mkdir()
        (self.tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (self.tmp_path / "apps" / "web").mkdir(parents=True)
        (self.tmp_path / "apps" / "web" / "package.json").write_text('{"name": "web"}')
        (self.tmp_path / "README.md").write_text("# demo")
        (self.tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        self.snapshot = LocalDirSnapshot(self.tmp_path)

    def test_lists_files_posix_relative_without_git_dir(self):
        self.assertEqual(
            self.snapshot.list_files(),
            ["README.md", "apps/web/package.json", "logo.png"],
        )

    def test_reads_text_and_returns_none_for_binary_or_missing(self):
        self.assertEqual(self.snapshot.read_file("apps/web/package.json"), '{"name": "web"}')
        self.assertIsNone(self.snapshot.read_file("logo.png"))
        self.assertIsNone(self.snapshot.read_file("nope.txt"))

    def test_cannot_escape_the_root(self):
        self.assertIsNone(self.snapshot.read_file("../../etc/passwd"))

    def test_missing_directory_is_an_error_up_front(self):
        with self.assertRaises(FileNotFoundError):
            LocalDirSnapshot(self.tmp_path / "missing")
