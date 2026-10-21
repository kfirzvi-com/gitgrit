"""The score representation GitGrit uses: the one switch for how every score
is shown."""
from app.domain.score_representation.letter_score_representation import LetterScoreRepresentation
from app.domain.score_representation.score_representation import ScoreRepresentation

SCORE_REPRESENTATION: ScoreRepresentation = LetterScoreRepresentation()
