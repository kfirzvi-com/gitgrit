"""Standard levels: how much a standard attached to a project weighs on its
grade. Pure rules, no I/O, no ORM.

The level lives on the link between a project and a standard
(``ProjectStandard.level``, snapshot on ``StandardExecution.level``), so the
same standard can gate one project and not another. ``LEVEL_RULES`` is the
one place a level is defined, behavior included: every way a level changes
the grade, the letters, the alerts and the screens is a field of its
``LevelRule``. Add a member to ``StandardLevel`` and its row here, and the
model choices, the standards table (column, bulk actions, filter), the
grade and the API follow. Code never compares a level to ``CRITICAL``; it
reads the field of its rule (``rule_for(level).gates_grade``).

To add a level: add the ``StandardLevel`` member (its value at most
``MAX_LENGTH`` characters, the model fields' size), add its ``LEVEL_RULES``
row, run ``makemigrations`` (an AlterField on ``ProjectStandard.level`` and
``StandardExecution.level``, and the two "level known" CheckConstraints),
regenerate ``cli/openapi.yaml`` (``make -C cli spec``), and update
``tests/domain/test_levels.py`` and ``site/docs/features/grades.md``.

To add a behavior (a new ``LevelRule`` field): add the field with a comment
saying what it does and which function reads it, set it on every
``LEVEL_RULES`` row (each field is required), and read it in the one place
the behavior happens, through ``rule_for(level).<field>`` or
``result.rule.<field>`` (a ``grading.Result`` or a ``StandardExecution``,
read with its own level): the grade, reasons, letters and alerts in
``app.domain.grading``; the counts, "Needs attention" and the Results tab
order in ``app.application.standard_results``; a set of standard ids with
``ProjectGrading.standard_ids_where(lambda rule: rule.<field>)``; templates
with ``ex.rule.<field>`` or ``rule.<field>``. Never reuse a field for a new
meaning, and take user-facing wording from ``label`` / ``help``. No
migration: behavior lives in code. Test the field per level and the
behavior through its reader in ``tests/domain/test_levels.py``, and update
``site/docs/features/grades.md``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class StandardLevel(StrEnum):
    HIGH = "high"
    CRITICAL = "critical"


# Every attachment starts here.
DEFAULT_LEVEL = StandardLevel.HIGH


@dataclass(frozen=True)
class LevelRule:
    level: StandardLevel
    label: str
    # A failing or unverified result makes the project grade an F
    # (``grading.is_gated``, ``grading.letter_for``).
    gates_grade: bool
    # The result counts toward the project's pass rate, which sets the
    # letter when nothing gates (``grading.letter_for``, ``reason_for``).
    in_pass_rate: bool
    # The standard's own letter is pass or fail only, A or F, instead of
    # its score's band (``grading.standard_letter``).
    pass_or_fail_letter: bool
    # An error in the standard's own run sends the "could not verify"
    # alert (``grading.unverified_transition``).
    alerts_when_unverified: bool
    # Shown as critical: the level chip on a result, the "N critical
    # failed" counts, listed first on the Results tab and in "Needs
    # attention", red (failing) there instead of amber.
    shown_as_critical: bool
    # Display order, most severe first (table, bulk actions, filter, sort).
    order: int
    # One line for tooltips.
    help: str


LEVEL_RULES: dict[StandardLevel, LevelRule] = {
    StandardLevel.CRITICAL: LevelRule(
        level=StandardLevel.CRITICAL,
        label="Critical",
        gates_grade=True,
        in_pass_rate=False,
        pass_or_fail_letter=True,
        alerts_when_unverified=True,
        shown_as_critical=True,
        order=0,
        help="A failing or unverified result makes the project grade an F",
    ),
    StandardLevel.HIGH: LevelRule(
        level=StandardLevel.HIGH,
        label="High",
        gates_grade=False,
        in_pass_rate=True,
        pass_or_fail_letter=False,
        alerts_when_unverified=False,
        shown_as_critical=False,
        order=1,
        help="Counts toward the project's pass rate",
    ),
}

# Longest level value; the model fields' max_length must hold it.
MAX_LENGTH = 20


def rule_for(level: str | None) -> LevelRule:
    """The rule of ``level``; an unknown or empty value reads as the default
    (a row written by a newer release, or a run with no attachment). An
    unknown non-empty value is logged, so a bad stored level is visible."""
    try:
        return LEVEL_RULES[StandardLevel(level)]
    except ValueError:
        if level:
            logger.warning("Unknown standard level %r; reading it as %s", level, DEFAULT_LEVEL.value)
        return LEVEL_RULES[DEFAULT_LEVEL]


def ordered_rules() -> list[LevelRule]:
    """Every level's rule, most severe first."""
    return sorted(LEVEL_RULES.values(), key=lambda r: r.order)


def level_choices() -> list[tuple[str, str]]:
    """``(value, label)`` pairs for model and form choices, most severe first."""
    return [(r.level.value, r.label) for r in ordered_rules()]


class UnknownLevel(ValueError):
    """A value that names no level."""

    def __init__(self, value):
        names = ", ".join(r.level.value for r in ordered_rules())
        super().__init__(f"Unknown level {value!r}. Use one of: {names}.")
        self.value = value


def parse_level(value) -> StandardLevel:
    """The level a posted value names, in any case; raises ``UnknownLevel``
    when it names none, so a typo never quietly becomes the default."""
    try:
        return StandardLevel(str(value).strip().lower())
    except ValueError:
        raise UnknownLevel(value) from None
