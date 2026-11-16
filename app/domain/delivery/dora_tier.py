from __future__ import annotations

from enum import StrEnum


class DoraTier(StrEnum):
    """The DORA performance band for deployment frequency. ``NONE`` is a
    project with no deployments in the window: nothing to rank yet."""

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
