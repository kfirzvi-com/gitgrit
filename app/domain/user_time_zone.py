"""The time zone a person reads times in, for what GitGrit sends them outside
the browser (emails). Pages don't use it: they show times in the browser's
own zone (``static/app/local-time.js``).

Rules:
1. A time zone is one of the IANA names (``Asia/Jerusalem``); any other name
   is refused.
2. A user who never chose a time zone reads times in UTC.
3. A stored name that is no longer known reads as UTC, so an email never
   fails because of it.
4. Showing a moment in a user's time zone changes how it is written, never
   the moment itself (times are stored in UTC).
6. A user who has not chosen a time zone is asked once; either answer is a
   choice. (Rule 5, only the user sets their own, is the application's.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

UTC = "UTC"


class UnknownTimeZone(ValueError):
    """A name that is not an IANA time zone."""


@cache
def _known_names() -> frozenset[str]:
    return frozenset(available_timezones())


def _is_known(name: str) -> bool:
    return name in _known_names()


@dataclass(frozen=True)
class UserTimeZone:
    """A user's time zone, by its IANA name. Only a known name makes one
    (rule 1), however it is built."""

    name: str

    def __post_init__(self):
        if not _is_known(self.name):
            raise UnknownTimeZone(f"Unknown time zone: {self.name!r}")

    @classmethod
    def parse(cls, name: str) -> UserTimeZone:
        """The time zone named ``name``, or ``UnknownTimeZone`` (rule 1)."""
        return cls(name)

    @classmethod
    def of(cls, stored: str) -> UserTimeZone:
        """A stored choice, or UTC when there is none or it is no longer
        known (rules 2 and 3)."""
        return cls(stored) if _is_known(stored) else cls(UTC)

    @staticmethod
    def is_chosen(stored: str) -> bool:
        """Whether the user has chosen a time zone that is still known; if
        not, they are asked (rule 6). ``UTC`` saved by "Keep UTC" counts."""
        return _is_known(stored)

    def local(self, moment: datetime) -> datetime:
        """``moment`` on this time zone's clock: the same instant, written
        in this zone (rule 4)."""
        if moment.tzinfo is None:
            raise ValueError("A moment must carry its time zone; stored times are UTC.")
        return moment.astimezone(ZoneInfo(self.name))
