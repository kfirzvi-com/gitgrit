from __future__ import annotations

from enum import StrEnum


class LeadTimeStart(StrEnum):
    """When a change's lead time starts. It always ends when the change runs
    in production.

    * ``COMMIT`` — when each commit was written (DORA's definition, so the
      tier compares with DORA's published bands);
    * ``READY`` — when its pull request was ready for review;
    * ``MERGE`` — when its pull request was merged.

    A commit pushed without a pull request counts from when it was written
    whichever start is chosen."""

    COMMIT = "commit"
    READY = "ready"
    MERGE = "merge"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def phrase(self) -> str:
        """The start in a sentence: "from {phrase} to production"."""
        return _PHRASES[self]

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(start.value, start.label) for start in cls]


_LABELS = {
    LeadTimeStart.COMMIT: "Commit (DORA)",
    LeadTimeStart.READY: "Ready for review",
    LeadTimeStart.MERGE: "Merge",
}

_PHRASES = {
    LeadTimeStart.COMMIT: "commit",
    LeadTimeStart.READY: "ready for review",
    LeadTimeStart.MERGE: "merge",
}

_DESCRIPTIONS = {
    LeadTimeStart.COMMIT: "From when each commit was written to when it runs in production.",
    LeadTimeStart.READY: "From when a pull request was ready for review to when it runs in production.",
    LeadTimeStart.MERGE: "From when a pull request was merged to when it runs in production.",
}
