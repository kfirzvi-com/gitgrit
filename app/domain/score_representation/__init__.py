"""How scores are shown: a commit's score (and so a branch's and a project's)
and one standard's result on a commit, each 0-100. Pure, no I/O.

- ``ScoreRepresentation`` (strategy): turns a value into a
  ``RepresentedScore`` (text, tone, spoken form). Every screen, the README
  badge, the architecture diagrams and the notifications go through it.
- ``LetterScoreRepresentation``: "B" (A+ 100, A 90+, B 75+, C 60+, D below; F
  only when a Required standard failed).
- ``NumberScoreRepresentation``: "82".
- ``COMMIT_SCORE_REPRESENTATION``: how a commit's, a branch's and a project's
  score reads (letters). ``STANDARD_RESULT_REPRESENTATION``: how one
  standard's result on a commit reads (numbers). Changing either changes how
  those scores read everywhere; the value underneath (and the API's numbers)
  never change.
- ``ScoreTone``: the one list of colour bands (healthy, warning, caution,
  critical, severe, unknown); each score's representation decides which one
  it is in, and project and stack health are these same tones.
"""
from app.domain.score_representation.letter_score_representation import LetterScoreRepresentation
from app.domain.score_representation.number_score_representation import NumberScoreRepresentation
from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_representation import ScoreRepresentation
from app.domain.score_representation.score_representation_in_use import (
    COMMIT_SCORE_REPRESENTATION,
    STANDARD_RESULT_REPRESENTATION,
)
from app.domain.score_representation.score_tone import ScoreTone

__all__ = [
    "COMMIT_SCORE_REPRESENTATION",
    "STANDARD_RESULT_REPRESENTATION",
    "LetterScoreRepresentation",
    "NumberScoreRepresentation",
    "RepresentedScore",
    "ScoreRepresentation",
    "ScoreTone",
]
