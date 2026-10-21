"""The commit scoring policy GitGrit uses."""
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.required_gate_weighted_average_policy import RequiredGateWeightedAveragePolicy

COMMIT_SCORING_POLICY: CommitScoringPolicy = RequiredGateWeightedAveragePolicy()
