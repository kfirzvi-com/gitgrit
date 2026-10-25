from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.scoring.commit_score_outcome import CommitScoreOutcome
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.commit_scoring_policy_in_use import COMMIT_SCORING_POLICY
from app.domain.scoring.commit_standing import CommitStanding
from app.domain.scoring.expected_standards import ExpectedStandards
from app.domain.scoring.new_commit_score import NewCommitScore
from app.domain.scoring.standard_run_result import StandardRunResult
from app.domain.scoring.standard_run_results_on_commit import StandardRunResultsOnCommit
from app.domain.scoring.standard_run_status import StandardRunStatus


@dataclass(frozen=True)
class CheckRun:
    """One check of a commit: one run of the standards it expects on it. A
    commit reads its newest CheckRun, alone: an earlier run never fills in
    for a standard this one did not run.

    Built from facts, no database: the commit, the standards it expects,
    its own results (newest first), the expected standards' names (to name
    the ones that never ran) and the score it saved, if any. Then ask it:

    - ``decide()``: the score to save once none of its runs is going;
    - ``standing``: where it stands now (checking, no score, failed, scored);
    - ``latest_results`` and ``never_ran_ids``: what to list for it."""

    commit_sha: str
    expected: ExpectedStandards
    results: tuple[StandardRunResult, ...] = ()
    standard_names: Mapping[str, str] = field(default_factory=dict)
    saved: CommitScoreValue | None = None

    @property
    def running(self) -> bool:
        """One of its runs is still going."""
        return any(r.status == StandardRunStatus.RUNNING for r in self.results)

    @property
    def finished_results(self) -> list[StandardRunResult]:
        """Each expected standard's newest finished run in it (passed,
        failed or errored): what it is scored from."""
        return StandardRunResultsOnCommit(self.results).newest_finished_per_expected_standard(self.expected)

    @property
    def not_run(self) -> list[str]:
        """The names of the expected standards with no finished run in it."""
        missing = self.expected.without_finished_result(self.finished_results)
        return [self.standard_names.get(i, i) for i in missing]

    def decide(self, policy: CommitScoringPolicy = COMMIT_SCORING_POLICY) -> NewCommitScore | None:
        """The score it gives its commit, and the runs it was decided from.
        None while there is nothing to decide: no commit yet, nothing
        expected, or a run still going. Otherwise always a score, no score
        included ("X errored", "Y not run")."""
        if not self.commit_sha or not self.expected or self.running:
            return None
        finished = self.finished_results
        return NewCommitScore(policy.score_commit(finished, self.not_run), finished)

    @property
    def standing(self) -> CommitStanding | None:
        """Where it stands, its commit's when it is the commit's newest:
        checking while a run goes; otherwise the score it saved, or, if it
        saved none, the one it gives now. None when it expects nothing or has
        no commit."""
        if not self.expected:
            return None
        expected_count = len(self.expected)
        finished_count = len(self.finished_results)
        if self.running:
            return CommitStanding(CommitScoreOutcome.CHECKING, "", expected_count, finished_count)
        score = self.saved
        if score is None:
            decided = self.decide()
            if decided is None:
                return None
            score = decided.score
        return CommitStanding(score.outcome, score.reason, expected_count, finished_count, score.value)

    @property
    def outcome(self) -> CommitScoreOutcome | None:
        return self.standing.outcome if self.standing else None

    @property
    def latest_results(self) -> list[StandardRunResult]:
        """Its newest run of each standard it lists
        (``ExpectedStandards.lists_runs_of``), running ones included: what
        the Results tab shows for it. A run of a standard deleted since has
        no id; it is told apart by name."""
        seen, latest = set(), []
        for result in self.results:
            key = result.standard_id or result.standard_name
            if key in seen or not self.expected.lists_runs_of(result.standard_id):
                continue
            seen.add(key)
            latest.append(result)
        return latest

    @property
    def never_ran_ids(self) -> list[str]:
        """The expected standards with no run at all in it."""
        if not self.expected:
            return []
        return self.expected.without_any_run(r.standard_id for r in self.results)
