"""Importance: how much an attached standard matters to one project. Pure
rules, no I/O, no ORM.

Importance lives on the attachment (``ProjectStandard.importance``), not on
the standard, so the same standard can be Required on one project and Minor
on another. ``RULES`` is the one place an importance is defined; the model
choices, the standards table (column, bulk actions, filter) and the API all
read it.

Today importance is recorded and shown only; it does not change the score
yet. ``fails_project`` already says which importance will gate it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Importance(StrEnum):
    """Most important first: the declaration order is the display order."""

    REQUIRED = "required"
    MAJOR = "major"
    MINOR = "minor"


# Every attachment starts here.
DEFAULT = Importance.MAJOR

# Longest value; the model field's max_length must hold it.
MAX_LENGTH = 20


@dataclass(frozen=True)
class ImportanceRule:
    importance: Importance
    label: str
    # A failing result fails the whole project. Marks the importance in the
    # standards table (a lock and the help line under the standard's name).
    fails_project: bool
    # One line for tooltips and docs.
    help: str


RULES: dict[Importance, ImportanceRule] = {
    Importance.REQUIRED: ImportanceRule(
        Importance.REQUIRED,
        "Required",
        True,
        "If it fails, the project fails",
    ),
    Importance.MAJOR: ImportanceRule(
        Importance.MAJOR,
        "Major",
        False,
        "Counts fully toward this project's score",
    ),
    Importance.MINOR: ImportanceRule(
        Importance.MINOR,
        "Minor",
        False,
        "Counts less toward this project's score",
    ),
}


def rule_for(value: str | None) -> ImportanceRule:
    """The rule of ``value``; an unknown or empty value reads as the default."""
    try:
        return RULES[Importance(value)]
    except ValueError:
        return RULES[DEFAULT]


def ordered_rules() -> list[ImportanceRule]:
    """Every importance's rule, most important first."""
    return [RULES[i] for i in Importance]


def choices() -> list[tuple[str, str]]:
    """``(value, label)`` pairs for model and form choices, most important first."""
    return [(r.importance.value, r.label) for r in ordered_rules()]


class UnknownImportance(ValueError):
    """A value that names no importance."""

    def __init__(self, value):
        names = ", ".join(i.value for i in Importance)
        super().__init__(f"Unknown importance {value!r}. Use one of: {names}.")
        self.value = value


def parse(value) -> Importance:
    """The importance a posted value names, in any case; raises
    ``UnknownImportance`` when it names none, so a typo never quietly becomes
    the default."""
    try:
        return Importance(str(value).strip().lower())
    except ValueError:
        raise UnknownImportance(value) from None
