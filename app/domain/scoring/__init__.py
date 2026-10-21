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
- ``ExpectedStandards``: the standards a commit check must get a finished
  result of before the commit can be scored.
- ``StandardRunResultsOnCommit``: every run on a commit, across its checks.
- ``CommitScoringPolicy`` (strategy) and ``RequiredGateWeightedAveragePolicy``,
  the one in use (``COMMIT_SCORING_POLICY``): a Required standard that failed
  or errored makes the commit 0, otherwise the importance-weighted average.
- ``CommitScoreValue``: a commit's computed score: value, whether a Required
  standard failed it, and why.
- ``ScorableCommitCheck``: one commit check seen for scoring; once finished
  and complete it gives a ``NewCommitScore``, and it says where the commit
  stands (``CommitScoringState``: complete, in progress or incomplete).
- ``BranchCommitTimeline``: how a branch's commits and scores are ordered.

Each run keeps the importance its standard had when it ran, so changing
importance or attachments later never rescores a commit.
"""
from app.domain.scoring.attached_standard import AttachedStandard
from app.domain.scoring.branch_commit_timeline import BranchCommitTimeline
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.commit_scoring_policy_in_use import COMMIT_SCORING_POLICY
from app.domain.scoring.commit_scoring_state import CommitScoringState
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
    "CommitScoreValue",
    "CommitScoringPolicy",
    "CommitScoringState",
    "ExpectedStandards",
    "NewCommitScore",
    "RequiredGateWeightedAveragePolicy",
    "ScorableCommitCheck",
    "StandardRunResult",
    "StandardRunResultsOnCommit",
    "StandardRunStatus",
]
