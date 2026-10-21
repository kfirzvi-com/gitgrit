"""The score representations GitGrit uses: one switch each for how a commit's
score and how one standard's result read."""
from app.domain.score_representation.letter_score_representation import LetterScoreRepresentation
from app.domain.score_representation.number_score_representation import NumberScoreRepresentation
from app.domain.score_representation.score_representation import ScoreRepresentation

# A commit's score, and so a branch's and a project's (the newest scored
# commit on it): "B".
COMMIT_SCORE_REPRESENTATION: ScoreRepresentation = LetterScoreRepresentation()

# One standard's result on a commit: "82".
STANDARD_RESULT_REPRESENTATION: ScoreRepresentation = NumberScoreRepresentation()
