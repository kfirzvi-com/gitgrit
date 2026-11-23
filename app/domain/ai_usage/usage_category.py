from __future__ import annotations

from enum import StrEnum


class UsageCategory(StrEnum):
    """What a workspace spent tokens on."""

    MAP = "map"  # inferring a project's dependencies and suggested projects (the diagrams)
    STANDARD = "standard"  # running LLM standards (standards whose evaluate takes the llm)

    @property
    def label(self) -> str:
        return {UsageCategory.MAP: "Dependency map", UsageCategory.STANDARD: "LLM standards"}[self]
