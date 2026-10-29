from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from providers.base import BaseProvider

# Where the host mounts an artifact project's commit (read-only).
PROJECT_ROOT = "/project"

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


class ArtifactProvider(BaseProvider):
    """An artifact project's files: one uploaded commit (e.g. a built app's
    dist), extracted and mounted at ``/project``. There is no repository
    behind it, so membership, contributors, topics and commit dates are
    empty; ``ref`` is the commit's SHA."""

    def __init__(self, project_id: str, full_path: str = "", ref: str = "", root: str = PROJECT_ROOT) -> None:
        self.project_id = project_id
        self.full_path = full_path
        self.ref = ref
        self.root = Path(root).resolve()
        self._files: list[str] | None = None

    def _resolve(self, path: str) -> Path | None:
        target = (self.root / path.lstrip("/")).resolve()
        if self.root not in target.parents:
            return None
        return target if target.is_file() else None

    def list_files(self) -> list[str]:
        if self._files is None:
            files = []
            for dirpath, _, names in os.walk(self.root):
                for name in names:
                    files.append((Path(dirpath) / name).relative_to(self.root).as_posix())
            self._files = sorted(files)
        return self._files

    def get_file_content(self, path: str) -> str | None:
        target = self._resolve(path)
        if target is None:
            return None
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None  # binary (images, audio, wasm): see get_file_size

    def get_file_size(self, path: str) -> int | None:
        target = self._resolve(path)
        return target.stat().st_size if target else None

    def get_languages(self) -> dict[str, float]:
        sizes: Counter = Counter()
        for path in self.list_files():
            lang = _LANGUAGES.get(os.path.splitext(path)[1].lower())
            if lang:
                sizes[lang] += self.get_file_size(path) or 0
        total = sum(sizes.values())
        if not total:
            return {}
        return {lang: round(100 * size / total, 1) for lang, size in sizes.most_common()}

    def get_members(self) -> list[dict]:
        return []

    def get_contributors(self) -> list[dict]:
        return []

    def get_default_branch(self) -> str:
        return ""

    def get_topics(self) -> list[str]:
        return []

    def get_metadata(self) -> dict:
        return {"name": self.full_path, "description": "", "web_url": "", "commit": self.ref}

    def get_file_last_commit_date(self, path: str) -> str | None:
        return None
