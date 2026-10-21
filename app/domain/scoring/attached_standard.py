from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AttachedStandard:
    """A standard attached to a project, as a commit check considers it."""

    standard_id: str
    enabled: bool
    draft: bool
    # Its criteria (events, Branch/Tag Filter, languages) match the commit:
    # ``standard_criteria.applies``, which knows nothing of the standard's
    # lifecycle.
    matches_criteria: bool

    @property
    def runs_on_commit(self) -> bool:
        """The standard runs on the commit: it is enabled, not a draft, and
        its criteria match."""
        return self.enabled and not self.draft and self.matches_criteria
