"""Project score: every rule about how a commit, a branch and a project are
scored. Pure, no I/O, no ORM; ``app.application.scoring`` loads the facts and
saves what these objects decide.

Vocabulary, one class per term:

- ``StandardRunStatus``: the status of one standard's run on a commit
  (running, passed, failed, error).
- ``StandardRunResult``: one standard's run on a commit: its status, the
  standard's own 0-100 score, and its importance when it ran.
- ``AttachedStandard``: a standard attached to the project, as a commit
  check considers it (does it run on the commit?).
- ``ExpectedStandards``: the standards a commit check expects a result of.
- ``StandardRunResultsOnCommit``: every run on a commit, across its checks.
- ``CommitScoringPolicy`` (strategy) and ``RequiredGateWeightedAveragePolicy``,
  the one in use (``COMMIT_SCORING_POLICY``): no score while an expected
  standard errored or never ran; otherwise a Required standard that failed
  fails the commit; otherwise the importance-weighted average.
- ``CommitScoreValue``: a commit's decided score: value (None when failed or
  no score), whether a Required standard failed it, and why.
- ``CommitScoreOutcome``: a commit's one outcome: checking, no score,
  failed or scored.
- ``ScorableCommitCheck``: one commit check seen for scoring; once none of
  its runs is going it gives a ``NewCommitScore``, and it says where the
  commit stands (``CommitStanding``: its outcome and how many standards
  finished).
- ``BranchCommitTimeline``: how a branch's commits and scores are ordered.

Each run keeps the importance its standard had when it ran, so changing
importance or attachments later never rescores a commit.
"""
from app.domain.scoring.attached_standard import AttachedStandard
from app.domain.scoring.branch_commit_timeline import BranchCommitTimeline
from app.domain.scoring.commit_score_outcome import CommitScoreOutcome
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.commit_scoring_policy_in_use import COMMIT_SCORING_POLICY
from app.domain.scoring.commit_standing import CommitStanding
from app.domain.scoring.expected_standards import ExpectedStandards
from app.domain.scoring.new_commit_score import NewCommitScore
from app.domain.scoring.required_gate_weighted_average_policy import RequiredGateWeightedAveragePolicy
from app.domain.scoring.scorable_commit_check import ScorableCommitCheck
from app.domain.scoring.standard_run_result import StandardRunResult
from app.domain.scoring.standard_run_results_on_commit import StandardRunResultsOnCommit
from app.domain.scoring.standard_run_status import StandardRunStatus

__all__ = [
    "COMMIT_SCORING_POLICY",
    "AttachedStandard",
    "BranchCommitTimeline",
    "CommitScoreOutcome",
    "CommitScoreValue",
    "CommitScoringPolicy",
    "CommitStanding",
    "ExpectedStandards",
    "NewCommitScore",
    "RequiredGateWeightedAveragePolicy",
    "ScorableCommitCheck",
    "StandardRunResult",
    "StandardRunResultsOnCommit",
    "StandardRunStatus",
]
