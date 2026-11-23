"""The languages a directory is written in, from its file names.

The platforms report languages per repository only. A project rooted inside a
monorepo needs its own list (standards filter on it), so it is counted from
the files under its root path.
"""
from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Iterable

# Extension -> language, named as GitHub's linguist names them so a standard's
# language criteria match whole-repository and rooted projects alike.
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


def languages_in(paths: Iterable[str]) -> list[str]:
    """The languages ``paths`` are written in, most files first."""
    counts: Counter[str] = Counter()
    for path in paths:
        name = posixpath.basename(path).lower()
        language = _BY_NAME.get(name) or _BY_EXTENSION.get(posixpath.splitext(name)[1])
        if language is None and name.startswith("dockerfile."):
            language = "Dockerfile"
        if language:
            counts[language] += 1
    return [language for language, _ in counts.most_common()]
