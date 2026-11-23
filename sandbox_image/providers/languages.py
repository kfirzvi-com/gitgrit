"""Extension -> language, for a project rooted inside a monorepo: the
platforms only report languages per repository, so the sandbox counts them
from the project's own files. Kept identical to
``app.domain.projects.languages`` (a test checks)."""
from __future__ import annotations

import posixpath
from collections import Counter

_BY_EXTENSION = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".tf": "HCL",
    ".hcl": "HCL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sql": "SQL",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
}
_BY_NAME = {"dockerfile": "Dockerfile", "makefile": "Makefile"}


def language_shares(paths: list[str]) -> dict[str, float]:
    """Each language's share (percent, by file count) of ``paths``."""
    counts: Counter[str] = Counter()
    for path in paths:
        name = posixpath.basename(path).lower()
        language = _BY_NAME.get(name) or _BY_EXTENSION.get(posixpath.splitext(name)[1])
        if language is None and name.startswith("dockerfile."):
            language = "Dockerfile"
        if language:
            counts[language] += 1
    total = sum(counts.values())
    return {lang: round(100 * n / total, 1) for lang, n in counts.most_common()} if total else {}
