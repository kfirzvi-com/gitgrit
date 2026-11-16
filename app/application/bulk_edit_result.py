from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BulkEditResult:
    """What one bulk change did (``ProjectBulkEdit``, ``StandardBulkEdit``,
    ``MarketplaceBulkInstall``, each in its own context): ``changed`` items, ``unchanged`` ones that
    already were as asked, and ``skipped`` ones it could not apply to, with
    why (``reason``). ``done`` says the change in words ("Disabled",
    "Set the owner of"); ``noun`` / ``noun_plural`` count the items."""

    done: str
    noun: str
    noun_plural: str
    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    reasons: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.skipped += 1
        if reason not in self.reasons:
            self.reasons.append(reason)

    def count(self, n: int) -> str:
        return f"{n} {self.noun if n == 1 else self.noun_plural}"

    @property
    def summary(self) -> str:
        """For a toast: "Disabled 3 standards; 1 already was. Skipped 1:
        drafts can't be enabled."""
        text = f"{self.done} {self.count(self.changed)}"
        if self.unchanged:
            text += f"; {self.unchanged} already {'was' if self.unchanged == 1 else 'were'}"
        text += "."
        if self.skipped:
            text += f" Skipped {self.skipped}: {'; '.join(self.reasons)}."
        return text

    @property
    def level(self) -> str:
        """The toast's level: a warning when anything was skipped."""
        return "warning" if self.skipped else "success"
