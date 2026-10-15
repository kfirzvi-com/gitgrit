"""Who is in a workspace, and as what: the roster's rules, without a
database. A workspace always has an owner; owners and admins manage people;
only owners make, change or remove owners."""
from unittest import TestCase

from app.domain.events import MemberJoined, MemberRemoved, MemberRoleChanged
from app.domain.workspace_roles import (
    ADMIN,
    MEMBER,
    OWNER,
    AlreadyMember,
    LastOwner,
    MembershipRuleError,
    NotAllowed,
    Roster,
    Seat,
    UnknownRole,
    found,
)


def roster(**seats):
    """roster(olga="owner", adam="admin") — user ids are the keyword names."""
    return Roster("ws", [Seat(user, role) for user, role in seats.items()], "Acme")


class FoundingTests(TestCase):
    def test_a_workspace_is_founded_with_its_owner(self):
        r, joined = found("ws", "olga", by_user_id="root", workspace_name="Acme")

        self.assertEqual(r.seat_of("olga"), Seat("olga", OWNER))
        self.assertEqual(joined, MemberJoined("ws", "olga", OWNER, "root"))

    def test_the_founder_cannot_be_anything_but_owner(self):
        for role in (ADMIN, MEMBER):
            with self.subTest(role=role), self.assertRaises(NotAllowed):
                found("ws", "olga", role=role)


class ChangeRoleTests(TestCase):
    def setUp(self):
        self.r = roster(olga=OWNER, adam=ADMIN, mia=MEMBER)

    def test_an_owner_makes_another_owner(self):
        event = self.r.change_role(self.r.actor("olga"), "mia", OWNER)

        self.assertEqual(event, MemberRoleChanged("ws", "mia", MEMBER, OWNER, "olga"))
        self.assertEqual(self.r.seat_of("mia").role, OWNER)
        self.assertEqual(self.r.owner_count, 2)

    def test_an_admin_manages_admins_and_members(self):
        self.r.change_role(self.r.actor("adam"), "mia", ADMIN)
        self.assertEqual(self.r.seat_of("mia").role, ADMIN)

    def test_an_admin_cannot_make_an_owner(self):
        with self.assertRaises(NotAllowed):
            self.r.change_role(self.r.actor("adam"), "mia", OWNER)
        self.assertEqual(self.r.seat_of("mia").role, MEMBER)

    def test_an_admin_cannot_touch_an_owner(self):
        self.r.change_role(self.r.actor("olga"), "mia", OWNER)
        with self.assertRaises(NotAllowed):
            self.r.change_role(self.r.actor("adam"), "mia", MEMBER)

    def test_a_member_changes_nobody(self):
        with self.assertRaises(NotAllowed):
            self.r.change_role(self.r.actor("mia"), "adam", MEMBER)

    def test_a_superuser_acts_as_an_owner_without_a_seat(self):
        root = self.r.actor("root", is_superuser=True)
        self.assertIsNone(self.r.seat_of("root"))

        self.r.change_role(root, "mia", OWNER)

        self.assertEqual(self.r.seat_of("mia").role, OWNER)

    def test_the_last_owner_cannot_step_down(self):
        with self.assertRaises(LastOwner) as raised:
            self.r.change_role(self.r.actor("olga"), "olga", ADMIN)
        self.assertIn('"Acme"', str(raised.exception))
        self.assertEqual(self.r.seat_of("olga").role, OWNER)

    def test_an_owner_steps_down_once_another_exists(self):
        self.r.change_role(self.r.actor("olga"), "adam", OWNER)
        self.r.change_role(self.r.actor("olga"), "olga", MEMBER)
        self.assertEqual(self.r.seat_of("olga").role, MEMBER)

    def test_two_owners_cannot_both_step_down(self):
        self.r.change_role(self.r.actor("olga"), "adam", OWNER)
        self.r.change_role(self.r.actor("adam"), "olga", MEMBER)
        with self.assertRaises(LastOwner):
            self.r.change_role(self.r.actor("adam"), "adam", MEMBER)

    def test_the_same_role_records_nothing(self):
        self.assertIsNone(self.r.change_role(self.r.actor("olga"), "mia", MEMBER))

    def test_unknown_role(self):
        with self.assertRaises(UnknownRole):
            self.r.change_role(self.r.actor("olga"), "mia", "god")

    def test_someone_outside_the_workspace(self):
        with self.assertRaises(MembershipRuleError):
            self.r.change_role(self.r.actor("olga"), "stranger", ADMIN)


class AddTests(TestCase):
    def setUp(self):
        self.r = roster(olga=OWNER, adam=ADMIN, mia=MEMBER)

    def test_an_admin_adds_members_and_admins(self):
        event = self.r.add(self.r.actor("adam"), "new", ADMIN)
        self.assertEqual(event, MemberJoined("ws", "new", ADMIN, "adam"))
        self.assertEqual(self.r.seat_of("new").role, ADMIN)

    def test_only_an_owner_adds_an_owner(self):
        with self.assertRaises(NotAllowed):
            self.r.add(self.r.actor("adam"), "new", OWNER)
        self.r.add(self.r.actor("olga"), "new", OWNER)
        self.assertEqual(self.r.owner_count, 2)

    def test_a_member_adds_nobody(self):
        with self.assertRaises(NotAllowed):
            self.r.add(self.r.actor("mia"), "new", MEMBER)

    def test_nobody_joins_twice(self):
        with self.assertRaises(AlreadyMember):
            self.r.add(self.r.actor("olga"), "mia", ADMIN)


class RemoveTests(TestCase):
    def setUp(self):
        self.r = roster(olga=OWNER, adam=ADMIN, mia=MEMBER)

    def test_an_admin_removes_a_member(self):
        event = self.r.remove(self.r.actor("adam"), "mia")
        self.assertEqual(event, MemberRemoved("ws", "mia", "adam"))
        self.assertIsNone(self.r.seat_of("mia"))

    def test_an_admin_cannot_remove_an_owner(self):
        self.r.change_role(self.r.actor("olga"), "mia", OWNER)
        with self.assertRaises(NotAllowed):
            self.r.remove(self.r.actor("adam"), "olga")

    def test_an_owner_removes_another_owner_but_never_the_last(self):
        self.r.change_role(self.r.actor("olga"), "mia", OWNER)
        self.r.remove(self.r.actor("olga"), "mia")
        with self.assertRaises(LastOwner):
            self.r.remove(self.r.actor("root", is_superuser=True), "olga")

    def test_a_member_removes_nobody_but_may_leave(self):
        with self.assertRaises(NotAllowed):
            self.r.remove(self.r.actor("mia"), "adam")
        self.assertEqual(self.r.remove(self.r.actor("mia"), "mia"), MemberRemoved("ws", "mia", "mia"))

    def test_the_last_owner_cannot_leave(self):
        with self.assertRaises(LastOwner):
            self.r.remove(self.r.actor("olga"), "olga")

    def test_losing_a_seat_without_anyone_deciding(self):
        self.r.ensure_can_lose("adam")
        with self.assertRaises(LastOwner):
            self.r.ensure_can_lose("olga")


class WhatEachPersonMayDoTests(TestCase):
    """What the member list offers each viewer."""

    def setUp(self):
        self.r = roster(olga=OWNER, adam=ADMIN, mia=MEMBER)

    def test_an_owner_may_give_any_role_except_to_the_last_owner(self):
        olga = self.r.actor("olga")
        self.assertEqual(self.r.assignable_roles(olga, "mia"), (OWNER, ADMIN, MEMBER))
        self.assertEqual(self.r.assignable_roles(olga, "olga"), ())
        self.assertEqual(self.r.assignable_roles(olga), (OWNER, ADMIN, MEMBER))

    def test_an_admin_may_give_admin_or_member_and_leaves_owners_alone(self):
        adam = self.r.actor("adam")
        self.assertEqual(self.r.assignable_roles(adam, "mia"), (ADMIN, MEMBER))
        self.assertEqual(self.r.assignable_roles(adam, "olga"), ())
        self.assertEqual(self.r.assignable_roles(adam), (ADMIN, MEMBER))

    def test_a_member_may_give_nothing(self):
        self.assertEqual(self.r.assignable_roles(self.r.actor("mia"), "adam"), ())

    def test_who_may_be_removed(self):
        self.assertTrue(self.r.can_remove(self.r.actor("adam"), "mia"))
        self.assertFalse(self.r.can_remove(self.r.actor("adam"), "olga"))
        self.assertFalse(self.r.can_remove(self.r.actor("olga"), "olga"))

    def test_only_owners_delete_the_workspace(self):
        self.assertTrue(self.r.can_delete_workspace(self.r.actor("olga")))
        self.assertTrue(self.r.can_delete_workspace(self.r.actor("x", is_superuser=True)))
        self.assertFalse(self.r.can_delete_workspace(self.r.actor("adam")))
