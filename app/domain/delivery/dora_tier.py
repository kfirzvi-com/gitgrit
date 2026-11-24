from __future__ import annotations

from enum import StrEnum


class DoraTier(StrEnum):
    """A DORA performance band, for deployment frequency or lead time for
    changes. ``NONE`` is a project with nothing in the window to rank yet."""

    ELITE = "elite"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def cadence(self) -> str:
        """The deployment habit the tier stands for, in plain words."""
        return _CADENCES[self]

    @property
    def lead_time(self) -> str:
        """The lead time the tier stands for, in plain words."""
        return _LEAD_TIMES[self]


_LABELS = {
    DoraTier.ELITE: "Elite",
    DoraTier.HIGH: "High",
    DoraTier.MEDIUM: "Medium",
    DoraTier.LOW: "Low",
    DoraTier.NONE: "No data",
}

_CADENCES = {
    DoraTier.ELITE: "On demand: deploys most days",
    DoraTier.HIGH: "Deploys every week",
    DoraTier.MEDIUM: "Deploys every month",
    DoraTier.LOW: "Deploys less than once a month",
    DoraTier.NONE: "No deployments yet",
}

_LEAD_TIMES = {
    DoraTier.ELITE: "Changes reach production within a day",
    DoraTier.HIGH: "Changes reach production within a week",
    DoraTier.MEDIUM: "Changes reach production within a month",
    DoraTier.LOW: "Changes take over a month to reach production",
    DoraTier.NONE: "No changes shipped yet",
}
