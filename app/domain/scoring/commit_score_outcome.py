from __future__ import annotations

from enum import StrEnum


class CommitScoreOutcome(StrEnum):
    """What a complete commit check decided about its commit:

    - ``FAILED``: a Required standard failed or could not run. A verdict,
      not a number: the commit has no value.
    - ``SCORED``: a value from 0 to 100 (the importance-weighted average),
      even 0 when every standard failed but none is Required.
    - ``UNSCORED``: nothing could be averaged (every run errored)."""

    FAILED = "failed"
    SCORED = "scored"
    UNSCORED = "unscored"

    @classmethod
    def of(cls, value, failed: bool) -> "CommitScoreOutcome":
        if failed:
            return cls.FAILED
        return cls.UNSCORED if value is None else cls.SCORED
