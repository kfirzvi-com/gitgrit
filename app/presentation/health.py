"""Composite health for stacks and projects, surfaced as colour codes.

Health is what points an engineering leader at the things that need attention.
Today it's derived solely from the compliance score (latest policy results),
but it's structured as a set of *signals* so future inputs slot in without
touching callers:

  * DORA deployment frequency (planned) — add a deployment-frequency signal to
    ``project_level``.
  * Failing high-severity policies (planned) — add a severity signal that can
    push a node to ``CRITICAL`` regardless of the aggregate score.

A node's level is the worst across its signals; a stack's level is the worst
across its projects (so one failing project can't hide behind a healthy
average).
"""

HEALTHY = "healthy"
WARNING = "warning"
CRITICAL = "critical"
UNKNOWN = "unknown"

# Severity order. UNKNOWN ranks lowest so a project with data always wins over
# one without; CRITICAL ranks highest so worst-of surfaces it.
_RANK = {UNKNOWN: 0, HEALTHY: 1, WARNING: 2, CRITICAL: 3}

# Compliance-score thresholds (mirrors the score-badge thresholds).
HEALTHY_MIN = 80
WARNING_MIN = 50


def level_from_score(score):
    if score is None:
        return UNKNOWN
    if score >= HEALTHY_MIN:
        return HEALTHY
    if score >= WARNING_MIN:
        return WARNING
    return CRITICAL


def worst(levels):
    """Worst (most severe) level among those given; UNKNOWN if none rank."""
    ranked = [lvl for lvl in levels if lvl in _RANK]
    if not ranked:
        return UNKNOWN
    return max(ranked, key=lambda lvl: _RANK[lvl])


def project_level(score):
    """A project's overall health level.

    Extension point: combine more signals as they land, e.g.::

        return worst([
            level_from_score(score),
            deployment_frequency_level(...),   # DORA
            severity_level(...),               # failing high-severity policies
        ])
    """
    return level_from_score(score)


def stack_level(project_levels):
    """A stack is as healthy as its weakest project (worst-of)."""
    return worst(project_levels)
