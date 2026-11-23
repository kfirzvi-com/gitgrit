"""Where a workspace goes in the picker, and who may pin it."""
from unittest import TestCase

from app.domain.workspace_picker import PickerSection, PinEligibility


class TestPickerSection(TestCase):
    def test_section_of(self):
        cases = [
            (True, True, PickerSection.PINNED),
            (True, False, PickerSection.PINNED),
            (False, True, PickerSection.WORKSPACES),
            (False, False, PickerSection.SUPPORT),
        ]
        for pinned, member, section in cases:
            with self.subTest(pinned=pinned, member=member):
                assert PickerSection.of(pinned=pinned, member=member) is section

    def test_sections_run_pinned_then_own_then_support(self):
        assert list(PickerSection) == [
            PickerSection.PINNED, PickerSection.WORKSPACES, PickerSection.SUPPORT,
        ]


class TestPinEligibility(TestCase):
    def test_pin_needs_access(self):
        cases = [(True, False, True), (False, True, True), (True, True, True), (False, False, False)]
        for is_member, is_superuser, allowed in cases:
            with self.subTest(is_member=is_member, is_superuser=is_superuser):
                assert PinEligibility.allows(
                    is_member=is_member, is_superuser=is_superuser
                ) is allowed
