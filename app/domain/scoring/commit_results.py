from __future__ import annotations

from app.domain.scoring.expectation import Expectation
from app.domain.scoring.result import Result


class CommitResults:
    """Every result on a commit, across all of its checks, newest first."""

    def __init__(self, newest_first):
        self._newest_first = list(newest_first)

    def for_expectation(self, expectation: Expectation) -> list[Result]:
        """The results the commit is scored from: for each expected standard,
        its newest finished result. A standard run again on the same commit
        replaces its earlier result."""
        wanted = {str(i) for i in expectation.standard_ids}
        picked = {}
        for result in self._newest_first:
            key = str(result.standard_id)
            if result.finished and key in wanted and key not in picked:
                picked[key] = result
        return list(picked.values())
