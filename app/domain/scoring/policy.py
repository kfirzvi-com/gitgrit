"""The scoring policy in use."""
from app.domain.scoring.required_gate_weighted_average import RequiredGateWeightedAverage
from app.domain.scoring.scoring_policy import ScoringPolicy

POLICY: ScoringPolicy = RequiredGateWeightedAverage()
