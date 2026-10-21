from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedStandards:
    """The standards a commit check must get a finished result of before
    its commit can be scored (standard ids)."""

    standard_ids: tuple

    @classmethod
    def from_attached(cls, attached_standards) -> "ExpectedStandards":
        """The attached standards that run on the commit."""
        return cls(tuple(str(s.standard_id) for s in attached_standards if s.runs_on_commit))

    def __bool__(self) -> bool:
        return bool(self.standard_ids)

    def __len__(self) -> int:
        return len(self.standard_ids)

    def lists_runs_of(self, standard_id) -> bool:
        """Does a commit whose newest check expects these standards list the
        runs of ``standard_id``? Only the expected ones: a standard detached
        (or no longer applying) since keeps its old run on record but is not
        part of the commit any more. Checks recorded before expectations
        existed list every run."""
        return not self.standard_ids or str(standard_id) in self.standard_ids

    def without_any_run(self, standard_ids_that_ran) -> list[str]:
        """The expected standards that never ran on the commit at all (not
        even one still running): what an incomplete commit is missing."""
        ran = {str(i) for i in standard_ids_that_ran}
        return [str(i) for i in self.standard_ids if str(i) not in ran]

    def without_finished_result(self, run_results) -> list[str]:
        """The expected standards with no finished run among ``run_results``:
        empty when the commit is complete."""
        finished = {str(r.standard_id) for r in run_results if r.is_finished}
        return [str(i) for i in self.standard_ids if str(i) not in finished]
