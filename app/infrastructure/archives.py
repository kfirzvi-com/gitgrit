"""Reading uploaded archives (zip, or tar in any compression) under the
rules in ``app.domain.uploads``.

``scan`` checks an archive without writing anything: it is what an upload
request runs before the archive is stored. ``extract`` writes the files of
an already-stored archive into a directory for the sandbox to read, and
re-applies every rule while it does, counting the bytes it actually writes
rather than trusting the sizes the archive declares.
"""
from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.domain.uploads import (
    DEFAULT_LIMITS,
    ArchiveLimits,
    UploadRejected,
    check_totals,
    member_path,
    strip_common_root,
)

_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Manifest:
    paths: list[str]  # project-relative, wrapping folder dropped
    total_bytes: int  # sum of the files' declared sizes
    root: str  # the wrapping folder dropped from every path ("" if none)
    sizes: dict[str, int]  # declared size of each path in ``paths``


@dataclass(frozen=True)
class _Member:
    path: str
    size: int
    open: callable  # -> binary file object


def _zip_members(data: bytes):
    archive = zipfile.ZipFile(io.BytesIO(data))
    for info in archive.infolist():
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise UploadRejected(f"Archive member {info.filename!r} is a link.")
        path = member_path(info.filename)
        if info.is_dir() or not path:
            continue
        yield _Member(path, info.file_size, lambda info=info: archive.open(info))


def _tar_members(data: bytes):
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        raise UploadRejected("Not a zip or tar archive.")
    for info in archive:
        if info.isdir():
            member_path(info.name)  # still refuse a directory outside the root
            continue
        if not info.isfile():
            raise UploadRejected(f"Archive member {info.name!r} is not a regular file.")
        path = member_path(info.name)
        if path:
            yield _Member(path, info.size, lambda info=info: archive.extractfile(info))


def _members(data: bytes):
    if zipfile.is_zipfile(io.BytesIO(data)):
        try:
            yield from _zip_members(data)
        except zipfile.BadZipFile as exc:
            raise UploadRejected(f"Corrupt zip archive: {exc}")
    else:
        yield from _tar_members(data)


def scan(data: bytes, limits: ArchiveLimits = DEFAULT_LIMITS) -> Manifest:
    """Check ``data`` against the upload rules and list its files. Raises
    ``UploadRejected`` naming the first rule it breaks."""
    if len(data) > limits.max_archive_bytes:
        raise UploadRejected(
            f"Archive is larger than {limits.max_archive_bytes // (1024 * 1024)} MB."
        )
    raw_paths: list[str] = []
    raw_sizes: list[int] = []
    seen: set[str] = set()
    total = 0
    for member in _members(data):
        if member.path in seen:
            raise UploadRejected(f"Archive lists {member.path!r} twice.")
        seen.add(member.path)
        raw_paths.append(member.path)
        raw_sizes.append(member.size)
        total += member.size
        check_totals(len(raw_paths), total, limits)
    if not raw_paths:
        raise UploadRejected("Archive has no files.")
    paths, root = strip_common_root(raw_paths)
    return Manifest(paths=paths, total_bytes=total, root=root, sizes=dict(zip(paths, raw_sizes)))


def read_file(data: bytes, path: str, limits: ArchiveLimits = DEFAULT_LIMITS) -> bytes | None:
    """The bytes of one file of the archive, by its project-relative path
    (as ``scan`` lists it), or None when there is no such file. Reads at
    most the extraction cap, like ``extract``."""
    root = scan(data, limits).root
    wanted = f"{root}/{path}" if root else path
    for member in _members(data):
        if member.path == wanted:
            with member.open() as src:
                content = src.read(limits.max_extracted_bytes + 1)
            check_totals(1, len(content), limits)
            return content
    return None


def extract(data: bytes, dest: Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> list[str]:
    """Write the archive's files under ``dest`` (which must exist), the
    wrapping folder dropped as ``scan`` does. Returns the project-relative
    paths written."""
    root = scan(data, limits).root
    written: list[str] = []
    total = 0
    dest = dest.resolve()
    for member in _members(data):
        path = member.path[len(root) + 1 :] if root else member.path
        target = (dest / path).resolve()
        if dest not in target.parents:
            raise UploadRejected(f"Archive member {member.path!r} points outside the archive.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with member.open() as src, open(target, "wb") as out:
            while chunk := src.read(_CHUNK):
                total += len(chunk)
                check_totals(len(written) + 1, total, limits)
                out.write(chunk)
        written.append(path)
    return written

