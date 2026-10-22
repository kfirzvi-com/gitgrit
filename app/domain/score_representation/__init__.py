"""How scores are shown: a commit's score (and so a branch's and a project's)
and one standard's result on a commit, each 0-100. Pure, no I/O.

- ``ScoreRepresentation`` (strategy): turns a value into a
  ``RepresentedScore`` (text, tone, spoken form). Every screen, the README
  badge, the architecture diagrams and the notifications go through it.
- ``LetterScoreRepresentation``: "B" (A+ 100, A 90+, B 75+, C 60+, D below; F
  only when a Required standard failed).
- ``NumberScoreRepresentation``: "82".
- ``ScoreDisplay``: a workspace's preference for how a commit's, a branch's
  and a project's score reads: letters or numbers (``representation``).
  ``COMMIT_SCORE_REPRESENTATION`` is the default (letters), for anything
  outside a workspace. ``STANDARD_RESULT_REPRESENTATION``: how one
  standard's result on a commit reads (numbers). Changing either changes how
  those scores read everywhere; the value underneath (and the API's numbers)
  never change.
- ``ScoreTone``: the one list of health tones (healthy, needs attention,
  failed, unknown); a project's health is one of these tones.
- ``ScoreHealth``: the one rule from a score to its tone: healthy from 90,
  needs attention below, failed only when a Required standard failed.
"""
from app.domain.score_representation.letter_score_representation import LetterScoreRepresentation
from app.domain.score_representation.number_score_representation import NumberScoreRepresentation
from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_display import ScoreDisplay
from app.domain.score_representation.score_health import ScoreHealth
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
    "ScoreDisplay",
    "ScoreHealth",
    "ScoreRepresentation",
    "ScoreTone",
]
