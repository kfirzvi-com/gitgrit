"""Composite health for stacks and projects, surfaced as colour codes.

Health is what points an engineering leader at the things that need attention.
It derives from the project's grade letter (``app.domain.grading``): F is
``failing``, D and C are ``attention``, A+, A and B are ``good``, and a
project with no grade is ``unknown``. It is structured as a set of *signals*
so future inputs (DORA deployment frequency, for one) slot in without
touching callers.

A node's level is the worst across its signals; a stack's level is the worst
across its projects (so one failing project can't hide behind a healthy
average).
"""
from app.domain import grading

GOOD = grading.TONE_GOOD
ATTENTION = grading.TONE_ATTENTION
FAILING = grading.TONE_FAILING
UNKNOWN = grading.TONE_UNKNOWN

# Severity order. UNKNOWN ranks lowest so a project with data always wins over
# one without; FAILING ranks highest so worst-of surfaces it.
_RANK = {UNKNOWN: 0, GOOD: 1, ATTENTION: 2, FAILING: 3}


def level_from_letter(letter):
    """The health level a grade letter maps to (see the module doc)."""
    return grading.tone_for(letter)


def worst(levels):
    """Worst (most severe) level among those given; UNKNOWN if none rank."""
    ranked = [lvl for lvl in levels if lvl in _RANK]
    if not ranked:
        return UNKNOWN
    return max(ranked, key=lambda lvl: _RANK[lvl])


def project_level(letter):
    """A project's overall health level.

    Extension point: combine more signals as they land, e.g.::

        return worst([
            level_from_letter(letter),
            deployment_frequency_level(...),   # DORA
        ])
    """
    return level_from_letter(letter)


def stack_level(project_levels):
    """A stack is as healthy as its weakest project (worst-of)."""
    return worst(project_levels)
