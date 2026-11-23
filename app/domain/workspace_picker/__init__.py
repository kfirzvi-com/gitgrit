"""The navbar workspace picker: which workspaces go where. Pure Python.

Pinned workspaces lead, then the user's own, then — for a superuser — the
workspaces they can only open as support. A pin is a preference, never
access: only a workspace the user can already open may be pinned.
"""
from app.domain.workspace_picker.picker_section import PickerSection
from app.domain.workspace_picker.pin_eligibility import PinEligibility

__all__ = ["PickerSection", "PinEligibility"]
