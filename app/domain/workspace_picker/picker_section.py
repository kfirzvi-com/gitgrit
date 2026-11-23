from __future__ import annotations

from enum import Enum


class PickerSection(Enum):
    """A group of rows in the workspace picker, in the order they show."""

    PINNED = "pinned"
    WORKSPACES = "workspaces"
    SUPPORT = "support"

    @classmethod
    def of(cls, *, pinned: bool, member: bool) -> PickerSection:
        """Where a workspace goes. A pin wins over everything: a pinned
        support workspace sits with the pins, not at the bottom."""
        if pinned:
            return cls.PINNED
        if member:
            return cls.WORKSPACES
        return cls.SUPPORT

    @property
    def title(self) -> str:
        return _TITLES[self]


_TITLES = {
    PickerSection.PINNED: "Pinned",
    PickerSection.WORKSPACES: "Workspaces",
    PickerSection.SUPPORT: "Support",
}
