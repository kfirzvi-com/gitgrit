"""Repository paths nobody should read for dependency evidence.

Shared by the model toolbox (hides them from listings) and the link candidate
scanner (skips them), so both agree on what a noise directory is.
"""
from __future__ import annotations

from collections.abc import Container

# Directories that are never dependency evidence and routinely dwarf the rest
# of the tree (committed node_modules, build output).
NOISE_DIRS = frozenset({
    "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".git", ".terraform", ".venv", "venv", ".idea", ".vscode",
})


def in_dirs(path: str, names: Container[str]) -> bool:
    """True when any directory on ``path`` (not its basename) is in ``names``."""
    return any(part in names for part in path.split("/")[:-1])


def is_noise(path: str) -> bool:
    return in_dirs(path, NOISE_DIRS)
