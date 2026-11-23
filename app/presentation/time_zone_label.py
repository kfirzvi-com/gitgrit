"""How a schedule's time zone is named on its chip."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeZoneLabel:
    """An IANA zone by its place: "Europe/Madrid" is "Madrid",
    "America/Argentina/Buenos_Aires" is "Buenos Aires"; "UTC" stays."""

    zone: str

    @property
    def text(self) -> str:
        return self.zone.rsplit("/", 1)[-1].replace("_", " ") if self.zone else ""
