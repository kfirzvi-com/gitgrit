from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, order=True)
class BillingMonth:
    """A calendar month usage is counted over. Months are in UTC for every
    workspace, so a meter never depends on who reads it."""

    year: int
    month: int

    @classmethod
    def of(cls, day: date) -> BillingMonth:
        return cls(day.year, day.month)

    @classmethod
    def parse(cls, text: str) -> BillingMonth | None:
        """The month ``YYYY-MM`` names, or None when it names none."""
        try:
            year, month = (int(part) for part in (text or "").split("-"))
            date(year, month, 1)
        except ValueError:
            return None
        return cls(year, month)

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return self.next().first_day - timedelta(days=1)

    @property
    def length(self) -> int:
        """How many days the month has."""
        return self.last_day.day

    def next(self) -> BillingMonth:
        return BillingMonth(self.year + self.month // 12, self.month % 12 + 1)

    def previous(self) -> BillingMonth:
        return BillingMonth(self.year - (self.month == 1), (self.month - 2) % 12 + 1)

    def days(self) -> list[date]:
        return [self.first_day + timedelta(days=i) for i in range(self.length)]

    @property
    def label(self) -> str:
        return self.first_day.strftime("%B %Y")

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"
