"""Reading uploaded archives safely (``app.infrastructure.archives``)."""
import io
import stat
import tarfile
import zipfile

from django.test import SimpleTestCase

from app.domain.uploads import ArchiveLimits, UploadRejected
from app.infrastructure import archives
from tests.support import TmpPathMixin


def make_zip(files: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, target)
    return buf.getvalue()


def make_tgz(files: dict[str, bytes], symlinks: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            t.addfile(info)
    return buf.getvalue()


GAME = {"dist/index.html": b"<html></html>", "dist/assets/app.js": b"console.log(1)"}


class ScanTests(SimpleTestCase):
    def test_a_zip_is_listed_without_its_wrapping_folder(self):
        manifest = archives.scan(make_zip(GAME))
        self.assertEqual(sorted(manifest.paths), ["assets/app.js", "index.html"])
        self.assertEqual(manifest.root, "dist")
        self.assertEqual(manifest.total_bytes, 13 + 14)

    def test_a_tar_gz_is_read_the_same_way(self):
        manifest = archives.scan(make_tgz(GAME))
        self.assertEqual(sorted(manifest.paths), ["assets/app.js", "index.html"])

    def test_zip_slip_is_rejected(self):
        with self.assertRaises(UploadRejected):
            archives.scan(make_zip({"../../etc/cron.d/x": b"x"}))

    def test_links_are_rejected(self):
        with self.assertRaisesMessage(UploadRejected, "is a link"):
            archives.scan(make_zip({"a.js": b"x"}, links={"b.js": "/etc/passwd"}))
        with self.assertRaisesMessage(UploadRejected, "not a regular file"):
            archives.scan(make_tgz({"a.js": b"x"}, symlinks={"b.js": "/etc/passwd"}))

    def test_an_archive_over_the_size_cap_is_rejected(self):
        with self.assertRaisesMessage(UploadRejected, "larger than"):
            archives.scan(make_zip(GAME), ArchiveLimits(max_archive_bytes=10))

    def test_an_archive_expanding_past_the_cap_is_rejected(self):
        bomb = make_zip({"zeros.bin": b"\0" * 100_000})
        with self.assertRaisesMessage(UploadRejected, "expands to more than"):
            archives.scan(bomb, ArchiveLimits(max_extracted_bytes=50_000))

    def test_an_empty_archive_is_rejected(self):
        with self.assertRaisesMessage(UploadRejected, "no files"):
            archives.scan(make_zip({}))

    def test_bytes_that_are_no_archive_are_rejected(self):
        with self.assertRaisesMessage(UploadRejected, "Not a zip or tar"):
            archives.scan(b"definitely not an archive")


class ExtractTests(TmpPathMixin, SimpleTestCase):
    def test_files_are_written_under_the_destination(self):
        written = archives.extract(make_zip(GAME), self.tmp_path)
        self.assertEqual(sorted(written), ["assets/app.js", "index.html"])
        self.assertEqual((self.tmp_path / "assets/app.js").read_bytes(), b"console.log(1)")

    def test_extraction_counts_real_bytes_not_declared_ones(self):
        data = make_tgz({"big.bin": b"\0" * 10_000})
        with self.assertRaises(UploadRejected):
            archives.extract(data, self.tmp_path, ArchiveLimits(max_extracted_bytes=5_000))


class ReadFileTests(SimpleTestCase):
    def test_a_file_is_read_by_its_path_without_the_wrapping_folder(self):
        self.assertEqual(archives.read_file(make_tgz(GAME), "assets/app.js"), b"console.log(1)")

    def test_a_missing_file_is_none(self):
        self.assertIsNone(archives.read_file(make_zip(GAME), "nope.js"))

    def test_sizes_are_listed_per_file(self):
        self.assertEqual(
            archives.scan(make_zip(GAME)).sizes, {"index.html": 13, "assets/app.js": 14}
        )
