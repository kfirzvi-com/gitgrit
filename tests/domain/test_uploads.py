"""What an uploaded archive may contain (``app.domain.uploads``)."""
from django.test import SimpleTestCase

from app.domain.uploads import (
    ArchiveLimits,
    UploadRejected,
    check_totals,
    content_digest,
    languages_from_paths,
    member_path,
    strip_common_root,
)


class MemberPathTests(SimpleTestCase):
    def test_a_plain_relative_path_is_kept(self):
        self.assertEqual(member_path("assets/app.js"), "assets/app.js")

    def test_dot_segments_and_extra_slashes_are_normalised(self):
        self.assertEqual(member_path("./assets//app.js"), "assets/app.js")
        self.assertEqual(member_path("assets/"), "assets")

    def test_windows_separators_count_as_slashes(self):
        self.assertEqual(member_path("assets\\app.js"), "assets/app.js")

    def test_an_absolute_path_is_rejected(self):
        for name in ("/etc/passwd", "C:/Windows/x.dll", "\\server\\x"):
            with self.subTest(name=name), self.assertRaises(UploadRejected):
                member_path(name)

    def test_a_path_climbing_out_is_rejected(self):
        for name in ("../x", "a/../../x", "a/..\\..\\x"):
            with self.subTest(name=name), self.assertRaises(UploadRejected):
                member_path(name)


class StripCommonRootTests(SimpleTestCase):
    def test_a_single_wrapping_folder_is_dropped(self):
        paths, root = strip_common_root(["dist/index.html", "dist/assets/app.js"])
        self.assertEqual(paths, ["index.html", "assets/app.js"])
        self.assertEqual(root, "dist")

    def test_files_already_at_the_root_are_kept(self):
        paths, root = strip_common_root(["index.html", "assets/app.js"])
        self.assertEqual(paths, ["index.html", "assets/app.js"])
        self.assertEqual(root, "")

    def test_several_top_level_folders_are_kept(self):
        paths, root = strip_common_root(["a/x.js", "b/y.js"])
        self.assertEqual(paths, ["a/x.js", "b/y.js"])
        self.assertEqual(root, "")


class TotalsTests(SimpleTestCase):
    limits = ArchiveLimits(max_archive_bytes=10, max_extracted_bytes=100, max_files=3)

    def test_within_the_caps_passes(self):
        check_totals(3, 100, self.limits)

    def test_too_many_files_is_rejected(self):
        with self.assertRaisesMessage(UploadRejected, "more than 3 files"):
            check_totals(4, 1, self.limits)

    def test_expanding_past_the_cap_is_rejected(self):
        with self.assertRaises(UploadRejected):
            check_totals(1, 101, self.limits)


class DigestTests(SimpleTestCase):
    def test_the_digest_is_as_wide_as_a_git_sha_and_stable(self):
        digest = content_digest(b"game")
        self.assertEqual(len(digest), 40)
        self.assertEqual(digest, content_digest(b"game"))
        self.assertNotEqual(digest, content_digest(b"other game"))


class LanguagesTests(SimpleTestCase):
    def test_languages_come_from_extensions_most_files_first(self):
        paths = ["index.html", "a.js", "b.js", "c.mjs", "style.css", "logo.png"]
        self.assertEqual(languages_from_paths(paths), ["JavaScript", "HTML", "CSS"])

    def test_no_known_extension_means_no_language(self):
        self.assertEqual(languages_from_paths(["logo.png", "README"]), [])
