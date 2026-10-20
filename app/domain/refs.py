"""Pure helpers for the refs a standard reads: no Django, no I/O."""
from __future__ import annotations

import re

_REF_PREFIX = re.compile(r"^refs/(heads|tags)/")
_REGEX_CHARS = re.compile(r"[*+?()\[\]{}|\\]")


def bare_ref(ref: str | None) -> str:
    """Strip the refs/heads/ or refs/tags/ prefix a webhook ref carries."""
    return _REF_PREFIX.sub("", ref or "")


def literal_ref(pattern: str | None) -> str:
    """Return the branch or tag a Branch/Tag Filter names literally, or ""
    when the filter is empty or a regex. ``main`` and ``^main$`` both name
    ``main``; ``^release/.*`` names nothing, so runs fall back to the default
    branch."""
    name = (pattern or "").strip().removeprefix("^").removesuffix("$")
    if not name or _REGEX_CHARS.search(name):
        return ""
    return name


def home_branch(default_branch: str, criteria: dict) -> str:
    """The branch a standard's results count on: the one its Branch/Tag
    Filter names literally, else the project's default branch."""
    return literal_ref((criteria or {}).get("ref")) or default_branch
