from __future__ import annotations

from app.domain.schedules.cron_schedule import CronSchedule

DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
DAY_NUMBERS = {d[:3].lower(): i for i, d in enumerate(DAYS)}
MONTH_NUMBERS = {m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)}


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _is_number(token: str) -> bool:
    return token.isdigit()


class CronDescription:
    """A schedule in plain English, so nobody has to guess what each ``*``
    means: "Every day at 09:00", "Every 15 minutes", "At 02:30 on weekdays",
    "At 06:00 on day 1 of the month". Unusual combinations still read field by
    field; nothing is left as a bare ``*``."""

    def __init__(self, schedule: CronSchedule):
        self.minute, self.hour, self.dom, self.month, self.dow = schedule.fields

    # --- values ---------------------------------------------------------------

    @staticmethod
    def _number(token: str, names: dict[str, int]) -> int:
        return int(token) if _is_number(token) else names[token.lower()]

    def _day_name(self, token: str) -> str:
        return DAYS[self._number(token, DAY_NUMBERS) % 7]

    def _month_name(self, token: str) -> str:
        return MONTHS[self._number(token, MONTH_NUMBERS) - 1]

    @staticmethod
    def _clock(hour: int, minute: int) -> str:
        return f"{hour:02d}:{minute:02d}"

    def _words(self, field: str, name, unit: str) -> str:
        """Any field, item by item: ``*/2`` every 2nd unit, ``1-5`` a through b,
        ``3`` the value."""
        parts = []
        for item in field.split(","):
            base, _, step = item.partition("/")
            if base == "*" and step:
                parts.append(f"every {_ordinal(int(step))} {unit}")
            elif "-" in base:
                a, b = base.split("-", 1)
                text = f"{name(a)} through {name(b)}"
                parts.append(f"every {_ordinal(int(step))} {unit} from {text}" if step else text)
            elif step:
                parts.append(f"every {_ordinal(int(step))} {unit} from {name(base)}")
            else:
                parts.append(name(base))
        return _join(parts)

    # --- parts ------------------------------------------------------------------

    def _single_minute(self) -> int | None:
        return int(self.minute) if _is_number(self.minute) else None

    def _hours(self) -> list[int] | None:
        """The hours, when the field lists plain hours."""
        items = self.hour.split(",")
        return [int(h) for h in items] if all(_is_number(h) for h in items) else None

    def _time(self) -> tuple[str, bool]:
        """When in the day, and whether that is once or a few times a day
        (so "every day" reads naturally before it)."""
        minute, hours = self._single_minute(), self._hours()
        if minute is not None and hours is not None and len(hours) <= 6:
            return "at " + _join([self._clock(h, minute) for h in sorted(hours)]), True
        if minute is not None and self.hour == "*":
            return ("every hour" if minute == 0 else f"every hour at :{minute:02d}"), False
        if minute is not None and self.hour.startswith("*/"):
            every = int(self.hour[2:])
            text = f"every {every} hours" if every > 1 else "every hour"
            return (text if minute == 0 else f"{text} at :{minute:02d}"), False
        if minute is not None and "-" in self.hour and "," not in self.hour and "/" not in self.hour:
            a, b = (int(x) for x in self.hour.split("-"))
            return f"every hour from {self._clock(a, minute)} to {self._clock(b, minute)}", False
        if self.minute == "*":
            rate = "every minute"
        elif self.minute.startswith("*/"):
            rate = f"every {int(self.minute[2:])} minutes"
        else:
            rate = f"at minute {self._words(self.minute, str, 'minute')} past the hour"
        if self.hour == "*":
            return rate, False
        if hours is not None and len(hours) == 1:
            return f"{rate} from {self._clock(hours[0], 0)} to {self._clock(hours[0], 59)}", False
        if "-" in self.hour and "," not in self.hour and "/" not in self.hour:
            a, b = (int(x) for x in self.hour.split("-"))
            return f"{rate} from {self._clock(a, 0)} to {self._clock(b, 59)}", False
        return f"{rate}, during hour {self._words(self.hour, str, 'hour')}", False

    def _weekdays(self) -> str | None:
        if self.dow == "*":
            return None
        normal = self.dow.lower()
        if normal in ("1-5", "mon-fri"):
            return "weekdays"
        if normal in ("0,6", "6,0", "sat,sun", "sun,sat", "6,7", "6-7"):
            return "weekends"
        return self._words(self.dow, self._day_name, "day of the week")

    def _days_of_month(self) -> str | None:
        if self.dom == "*":
            return None
        if self.dom.startswith("*/"):
            return f"every {int(self.dom[2:])} days"
        if self.dom == "L":
            return "the last day of the month"
        items = self.dom.split(",")
        noun = "day" if len(items) == 1 and _is_number(items[0]) else "days"
        return f"{noun} {self._words(self.dom, str, 'day')} of the month"

    def _months(self) -> str | None:
        if self.month == "*":
            return None
        return "in " + self._words(self.month, self._month_name, "month")

    # --- the sentence -----------------------------------------------------------

    @property
    def text(self) -> str:
        time, daily = self._time()
        weekdays, days, months = self._weekdays(), self._days_of_month(), self._months()
        if weekdays and days:
            # Cron runs when either matches.
            when = f"on {days} or on {weekdays}" if not days.startswith("every") else f"{days} or on {weekdays}"
        elif weekdays:
            when = f"on {weekdays}"
        elif days:
            when = days if days.startswith("every") else f"on {days}"
        else:
            when = ""
        if not when and daily:
            sentence = f"every day {time}"
        else:
            sentence = " ".join(p for p in (time, when) if p)
        if months:
            sentence = f"{sentence} {months}"
        return sentence[0].upper() + sentence[1:]

    def __str__(self) -> str:
        return self.text
