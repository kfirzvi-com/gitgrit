"""The sandbox's upload provider reads a version's files from the directory
the host mounts at /project."""
import sys
from pathlib import Path

from django.test import SimpleTestCase

from tests.support import TmpPathMixin

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from providers.factory import create_provider  # noqa: E402
from providers.upload import UploadProvider  # noqa: E402


class UploadProviderTests(TmpPathMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        (self.tmp_path / "assets").mkdir()
        (self.tmp_path / "index.html").write_text("<html></html>")
        (self.tmp_path / "assets/app.js").write_text("x" * 300)
        (self.tmp_path / "assets/logo.png").write_bytes(b"\x89PNG\xff\xfe")
        self.provider = UploadProvider("ext-42", full_path="Storefront", ref="abc", root=str(self.tmp_path))

    def test_the_factory_picks_it_for_uploads_even_without_a_token(self):
        provider = create_provider(platform="upload", project_id="g", access_token=None)
        self.assertIsInstance(provider, UploadProvider)

    def test_files_are_listed_relative_to_the_project(self):
        self.assertEqual(
            self.provider.list_files(), ["assets/app.js", "assets/logo.png", "index.html"]
        )

    def test_text_files_are_read_and_binaries_are_not(self):
        self.assertEqual(self.provider.get_file_content("index.html"), "<html></html>")
        self.assertIsNone(self.provider.get_file_content("assets/logo.png"))
        self.assertIsNone(self.provider.get_file_content("missing.js"))

    def test_sizes_cover_binaries_too(self):
        self.assertEqual(self.provider.get_file_size("assets/logo.png"), 6)
        self.assertIsNone(self.provider.get_file_size("missing.js"))

    def test_nothing_outside_the_project_is_readable(self):
        outside = self.tmp_path.parent / "secret.txt"
        outside.write_text("secret")
        self.addCleanup(outside.unlink)
        self.assertIsNone(self.provider.get_file_content("../secret.txt"))
        self.assertIsNone(self.provider.get_file_size("/../secret.txt"))

    def test_languages_are_weighted_by_size(self):
        self.assertEqual(self.provider.get_languages(), {"JavaScript": 95.8, "HTML": 4.2})

    def test_repository_facts_are_empty(self):
        self.assertEqual(self.provider.get_members(), [])
        self.assertEqual(self.provider.get_contributors(), [])
        self.assertIsNone(self.provider.get_file_last_commit_date("index.html"))
        self.assertEqual(self.provider.get_metadata()["version"], "abc")
