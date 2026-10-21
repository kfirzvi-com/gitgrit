"""Composite health for stacks and projects, surfaced as colour codes.

Health is what points an engineering leader at the things that need attention.
Today it's derived solely from the compliance score (latest standard results),
but it's structured as a set of *signals* so future inputs slot in without
touching callers:

  * DORA deployment frequency (planned) — add a deployment-frequency signal to
    ``project_level``.
  * Failing high-severity standards (planned) — add a severity signal that can
    push a node to ``CRITICAL`` regardless of the aggregate score.

A node's level is the worst across its signals; a stack's level is the worst
across its projects (so one failing project can't hide behind a healthy
average).
"""

from app.domain.score_representation import COMMIT_SCORE_REPRESENTATION, ScoreTone

# Health levels are score tones (``ScoreTone``): one list, and the
# representation in use decides which one a score is in.
HEALTHY = ScoreTone.HEALTHY
WARNING = ScoreTone.WARNING
CAUTION = ScoreTone.CAUTION
CRITICAL = ScoreTone.CRITICAL
SEVERE = ScoreTone.SEVERE
UNKNOWN = ScoreTone.UNKNOWN


def level_from_score(score, failed: bool = False):
    """A score's health level: its tone (``COMMIT_SCORE_REPRESENTATION.tone``);
    ``failed`` marks a score a Required standard failed."""
    return COMMIT_SCORE_REPRESENTATION.tone(score, failed=failed)


def worst(levels):
    """Worst (most severe, ``ScoreTone.severity``) level among those given;
    UNKNOWN if none."""
    ranked = [ScoreTone(lvl) for lvl in levels if lvl in set(ScoreTone)]
    if not ranked:
        return UNKNOWN
    return max(ranked, key=lambda lvl: lvl.severity)


def project_level(score, failed: bool = False):
    """A project's overall health level.

    Extension point: combine more signals as they land, e.g.::

        return worst([
            level_from_score(score),
            deployment_frequency_level(...),   # DORA
            severity_level(...),               # failing high-severity standards
        ])
    """
    return level_from_score(score, failed=failed)


def stack_level(project_levels):
    """A stack is as healthy as its weakest project (worst-of)."""
    return worst(project_levels)
