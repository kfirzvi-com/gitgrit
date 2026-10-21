from __future__ import annotations

from app.domain.scoring.expected_standards import ExpectedStandards
from app.domain.scoring.standard_run_result import StandardRunResult


class StandardRunResultsOnCommit:
    """Every standard run on a commit, across all of its checks, newest
    first."""

    def __init__(self, newest_first):
        self._newest_first: list[StandardRunResult] = list(newest_first)

    def newest_finished_per_expected_standard(self, expected: ExpectedStandards) -> list[StandardRunResult]:
        """The runs a commit is scored from: for each expected standard, its
        newest finished run. A standard run again on the same commit replaces
        its earlier result."""
        wanted = {str(i) for i in expected.standard_ids}
        picked = {}
        for result in self._newest_first:
            key = str(result.standard_id)
            if result.is_finished and key in wanted and key not in picked:
                picked[key] = result
        return list(picked.values())
