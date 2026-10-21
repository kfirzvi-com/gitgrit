"""How scores are shown, everywhere: a project's, a branch's, a commit's and a
standard's 0-100 score. Pure, no I/O.

- ``ScoreRepresentation`` (strategy): turns a value into a
  ``RepresentedScore`` (text, tone, spoken form). Every screen, the README
  badge, the architecture diagrams and the notifications go through it.
- ``NumberScoreRepresentation``: "82", the representation in use.
- ``SCORE_REPRESENTATION``: the one in use. Changing it changes how every
  score reads; the value underneath (and the API's numbers) never change.
- ``ScoreTone``: the one list of colour bands (healthy, warning, critical,
  unknown); the representation holds the thresholds that pick one, and
  project and stack health are these same tones.
"""
from app.domain.score_representation.number_score_representation import NumberScoreRepresentation
from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_representation import ScoreRepresentation
from app.domain.score_representation.score_representation_in_use import SCORE_REPRESENTATION
from app.domain.score_representation.score_tone import ScoreTone

__all__ = [
    "SCORE_REPRESENTATION",
    "NumberScoreRepresentation",
    "RepresentedScore",
    "ScoreRepresentation",
    "ScoreTone",
]
