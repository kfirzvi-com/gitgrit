"""Project score: every rule about how a commit, a branch and a project are
scored. Pure, no I/O, no ORM; ``app.application.scoring`` loads the facts
and saves what these objects decide.

- ``Expectation`` (value object): the standards a check expects a finished
  result of, chosen from the project's ``Candidate`` standards.
- ``CommitResults`` (value object): every result on a commit; for an
  expectation, the newest finished result of each expected standard.
- ``ScoringPolicy`` (strategy): turns a complete commit's results into a
  ``Score``. ``RequiredGateWeightedAverage`` is the policy in use: a Required
  standard that failed or errored, for any reason, makes it 0; otherwise the
  average of the results' 0-100 scores weighted by importance, errors of
  other importances left out.
- ``Check`` (entity): one check of one commit; once finished and complete it
  scores its commit, and it says where the commit stands (``CommitState``).
- ``CommitTimeline``: how a branch's commits and scores are ordered, which
  score a commit keeps and which branch a commit is read on.

Each result carries the importance its standard had when it ran, so changing
importance or attachments later never rescores a commit.
"""
from app.domain.scoring.candidate import Candidate
from app.domain.scoring.check import Check
from app.domain.scoring.check_outcome import CheckOutcome
from app.domain.scoring.commit_results import CommitResults
from app.domain.scoring.commit_state import CommitState
from app.domain.scoring.commit_timeline import CommitTimeline
from app.domain.scoring.expectation import Expectation
from app.domain.scoring.policy import POLICY
from app.domain.scoring.required_gate_weighted_average import RequiredGateWeightedAverage
from app.domain.scoring.result import Result
from app.domain.scoring.score import Score
from app.domain.scoring.scoring_policy import ScoringPolicy
from app.domain.scoring.status import ERROR, FAILED, FINISHED, PASSED, RUNNING

__all__ = [
    "POLICY",
    "Candidate",
    "Check",
    "CheckOutcome",
    "CommitResults",
    "CommitState",
    "CommitTimeline",
    "ERROR",
    "Expectation",
    "FAILED",
    "FINISHED",
    "PASSED",
    "RUNNING",
    "RequiredGateWeightedAverage",
    "Result",
    "Score",
    "ScoringPolicy",
]
