"""Rules for artifact projects: what an uploaded archive may contain.

An artifact project's files arrive as an archive (zip or tar.gz) instead of
from a Git repository: e.g. a built app's dist, uploaded by hand or by the
system that produces it. Each upload is a commit (``ArtifactCommit``).

The archive is untrusted input. These rules decide what is accepted before
anything is written to disk: every member path must stay inside the project
(no absolute paths, no ``..``), only regular files and directories count
(links and devices are refused), and the total size and file count are
capped so a small archive cannot expand into a huge one. Reading the archive
format itself is infrastructure (``app.infrastructure.archives``).
"""
from __future__ import annotations

import hashlib
import posixpath
from collections import Counter
from dataclasses import dataclass

# Width of a Git commit SHA, which an uploaded commit's SHA matches.
SHA_LENGTH = 40


class UploadRejected(ValueError):
    """The uploaded archive breaks a rule; the message says which."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 200 * 1024 * 1024
    max_files: int = 20_000


DEFAULT_LIMITS = ArchiveLimits()


def commit_sha(data: bytes) -> str:
    """An uploaded commit's SHA: the first 40 hex characters of the
    archive's SHA-256. The same bytes uploaded twice are the same commit."""
    return hashlib.sha256(data).hexdigest()[:SHA_LENGTH]


def member_path(name: str) -> str:
    """``name`` as a project-relative path, or raise ``UploadRejected`` when it
    would land outside the project. Backslashes count as separators (zips
    written on Windows) and a leading ``./`` is dropped; the result has no
    leading or trailing slash."""
    raw = name.replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise UploadRejected(f"Archive member {name!r} has an absolute path.")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise UploadRejected(f"Archive member {name!r} points outside the archive.")
    return posixpath.join(*parts) if parts else ""


def strip_common_root(paths: list[str]) -> tuple[list[str], str]:
    """Drop a single top-level directory every file sits in (``dist/``,
    ``my-app-1.4/``), so a project reads the same whether it was archived
    from inside its folder or from outside it. Returns the stripped paths
    and the root that was dropped ("" when there was none)."""
    if not paths:
        return paths, ""
    heads = {p.split("/", 1)[0] for p in paths}
    if len(heads) != 1 or any("/" not in p for p in paths):
        return paths, ""
    root = heads.pop()
    return [p.split("/", 1)[1] for p in paths], root


def check_totals(file_count: int, extracted_bytes: int, limits: ArchiveLimits) -> None:
    """Raise ``UploadRejected`` once the archive's running totals pass the caps."""
    if file_count > limits.max_files:
        raise UploadRejected(f"Archive has more than {limits.max_files} files.")
    if extracted_bytes > limits.max_extracted_bytes:
        raise UploadRejected(
            f"Archive expands to more than {limits.max_extracted_bytes // (1024 * 1024)} MB."
        )


# Extension → language, for the project's language list (standards filter on
# it). Only what a built web app ships; anything else is not a language.
_LANGUAGES = {
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".wasm": "WebAssembly",
    ".py": "Python",
}


def languages_from_paths(paths: list[str]) -> list[str]:
    """The languages a set of files is written in, most files first."""
    counts = Counter(
        _LANGUAGES[ext]
        for ext in (posixpath.splitext(p)[1].lower() for p in paths)
        if ext in _LANGUAGES
    )
    return [lang for lang, _ in counts.most_common()]


@dataclass
class TreeNode:
    """A folder or file of an uploaded commit, for browsing. A folder's
    ``size`` and ``file_count`` cover everything under it."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    file_count: int = 0
    children: list["TreeNode"] | None = None

    @property
    def depth(self) -> int:
        """0 for a top-level entry, 1 inside one folder, and so on."""
        return self.path.count("/")


def file_tree(sizes: dict[str, int]) -> TreeNode:
    """The folder tree of a commit's files (path -> size): folders first,
    then files, each by name."""
    root = TreeNode(name="", path="", is_dir=True, children=[])
    folders = {"": root}
    for path in sorted(sizes):
        parent = root
        parts = path.split("/")
        for depth, part in enumerate(parts[:-1]):
            folder_path = "/".join(parts[: depth + 1])
            folder = folders.get(folder_path)
            if folder is None:
                folder = TreeNode(name=part, path=folder_path, is_dir=True, children=[])
                folders[folder_path] = folder
                parent.children.append(folder)
            parent = folder
        parent.children.append(TreeNode(name=parts[-1], path=path, is_dir=False, size=sizes[path]))

    def finish(node: TreeNode) -> None:
        for child in node.children:
            if child.is_dir:
                finish(child)
        node.children.sort(key=lambda c: (not c.is_dir, c.name.lower()))
        node.size = sum(c.size for c in node.children)
        node.file_count = sum(c.file_count if c.is_dir else 1 for c in node.children)

    finish(root)
    return root
