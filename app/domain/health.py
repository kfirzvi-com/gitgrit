"""A project's health, surfaced as colour codes.

Health is what points an engineering leader at the things that need attention:
healthy, needs attention, or failed (a Required standard failed), from the
project's commit score through ``ScoreHealth``. It's structured as a set of
*signals* so future inputs slot in without touching callers:

  * DORA deployment frequency (planned) — add a deployment-frequency signal to
    ``project_level``.

A project's level is the worst across its signals. Many projects together
(a stack, the workspace) never get one level: they are counted by health
(``app.application.project_health_counts``), where a project with no grade
counts as needing attention (``counted_level``).
"""

from app.domain.score_representation import ScoreHealth, ScoreTone

# Health levels are score tones (``ScoreTone``), one list for everything.
HEALTHY = ScoreTone.HEALTHY
NEEDS_ATTENTION = ScoreTone.NEEDS_ATTENTION
FAILED = ScoreTone.FAILED
UNKNOWN = ScoreTone.UNKNOWN


def level_from_score(score, failed: bool = False):
    """A score's health level (``ScoreHealth``), the same however the score reads;
    ``failed`` marks a score a Required standard failed."""
    return ScoreHealth.tone(score, failed=failed)


def worst(levels):
    """Worst (most severe, ``ScoreTone.severity``) level among those given;
    UNKNOWN if none."""
    ranked = [ScoreTone(lvl) for lvl in levels if lvl in set(ScoreTone)]
    if not ranked:
        return UNKNOWN
    return max(ranked, key=lambda lvl: lvl.severity)


def counted_level(level):
    """Which count a project goes in when projects are counted by health:
    its own level, except that a project with no grade (no score: a standard
    errored or never ran, no standards, never checked, or being checked)
    needs attention. There is no "no data" count."""
    level = ScoreTone(level)
    return NEEDS_ATTENTION if level is UNKNOWN else level


def project_level(score, failed: bool = False):
    """A project's overall health level.

    Extension point: combine more signals as they land, e.g.::

        return worst([
            level_from_score(score),
            deployment_frequency_level(...),   # DORA
        ])
    """
    return level_from_score(score, failed=failed)

