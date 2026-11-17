"""The time zone a user reads times in: a setting of the user (identity).

Rules:
1. A time zone is one of the IANA names (``Asia/Jerusalem``); any other name
   is refused.
2. A user who never chose a time zone reads times in UTC.
3. A stored name that is no longer known reads as UTC, so writing a time for
   the user never fails because of it.
4. Showing a moment in a user's time zone changes how it is written, never
   the moment itself (times are stored in UTC).
5. Only the user sets their own time zone (the application's rule:
   ``app.application.user_time_zone_setting``).
6. A user who has not chosen a time zone is asked once, with their device's
   zone as the suggestion; a device already on UTC, or on a zone GitGrit
   doesn't know, has nothing to suggest. Either answer is a choice; a user
   who ignores the question is not asked again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

UTC = "UTC"
# Names that are UTC by another name: a device on one has nothing to suggest.
UTC_NAMES = frozenset({"UTC", "Etc/UTC", "Etc/UCT", "UCT", "Etc/Universal", "Universal", "Etc/Zulu", "Zulu"})


class UnknownTimeZone(ValueError):
    """A name that is not an IANA time zone."""


@cache
def _names() -> tuple[str, ...]:
    return tuple(sorted(available_timezones()))


@cache
def _known_names() -> frozenset[str]:
    return frozenset(_names())


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
    def names() -> tuple[str, ...]:
        """Every known time zone name, sorted: the ones a user can pick."""
        return _names()

    @staticmethod
    def is_chosen(stored: str) -> bool:
        """Whether the user has chosen a time zone that is still known; if
        not, they are asked (rule 6). ``UTC`` saved by "Keep UTC" counts."""
        return _is_known(stored)

    @staticmethod
    def should_ask(stored: str, already_asked: bool) -> bool:
        """Whether to ask the user for their time zone: not chosen yet and
        not asked before (rule 6)."""
        return not _is_known(stored) and not already_asked

    @classmethod
    def suggestion_for(cls, device_zone: str) -> UserTimeZone | None:
        """The device's zone to suggest, or None when there is nothing to
        suggest: a zone GitGrit doesn't know, or UTC already (rule 6)."""
        if not _is_known(device_zone) or device_zone in UTC_NAMES:
            return None
        return cls(device_zone)

    def local(self, moment: datetime) -> datetime:
        """``moment`` on this time zone's clock: the same instant, written
        in this zone (rule 4)."""
        if moment.tzinfo is None:
            raise ValueError("A moment must carry its time zone; stored times are UTC.")
        return moment.astimezone(ZoneInfo(self.name))
