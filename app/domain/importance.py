"""Importance: how much an attached standard matters to one project. Pure,
no I/O, no ORM.

Importance lives on the attachment (``ProjectStandard.importance``), not on
the standard, so the same standard can be Required on one project and Minor
on another. It is recorded only; it does not change the score yet.
"""
from __future__ import annotations

from enum import StrEnum


class Importance(StrEnum):
    """Most important first: the declaration order is the display order."""

    REQUIRED = "required"
    MAJOR = "major"
    MINOR = "minor"

    @property
    def label(self) -> str:
        return self.value.capitalize()


# Every attachment starts here.
DEFAULT = Importance.MAJOR

# Longest value; the model field's max_length must hold it.
MAX_LENGTH = 20


def choices() -> list[tuple[str, str]]:
    """``(value, label)`` pairs for model and form choices, most important first."""
    return [(i.value, i.label) for i in Importance]


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
