"""Who runs GitGrit: only superusers make superusers, only active accounts
can be one, and there is always at least one."""
from unittest import TestCase

from app.domain.events import SuperuserGranted, SuperuserRevoked
from app.domain.superusers import (
    Account,
    LastSuperuser,
    NotAllowed,
    SuperuserRuleError,
    Superusers,
)


class GrantTests(TestCase):
    def setUp(self):
        self.supers = Superusers(["root"])

    def test_a_superuser_makes_another(self):
        event = self.supers.grant("root", Account("ada"))

        self.assertEqual(event, SuperuserGranted("ada", "root"))
        self.assertIn("ada", self.supers)

    def test_nobody_else_can(self):
        with self.assertRaises(NotAllowed):
            self.supers.grant("ada", Account("grace"))

    def test_only_active_accounts(self):
        with self.assertRaises(NotAllowed):
            self.supers.grant("root", Account("pending", is_active=False))
        self.assertNotIn("pending", self.supers)

    def test_not_twice(self):
        with self.assertRaises(SuperuserRuleError):
            self.supers.grant("root", Account("root", is_superuser=True))


class RevokeTests(TestCase):
    def setUp(self):
        self.supers = Superusers(["root", "ada"])

    def test_a_superuser_revokes_another(self):
        event = self.supers.revoke("root", Account("ada", is_superuser=True))

        self.assertEqual(event, SuperuserRevoked("ada", "root"))
        self.assertNotIn("ada", self.supers)

    def test_a_superuser_may_step_down_while_another_remains(self):
        self.supers.revoke("ada", Account("ada", is_superuser=True))
        self.assertEqual(len(self.supers), 1)

    def test_never_the_last(self):
        self.supers.revoke("root", Account("ada", is_superuser=True))
        with self.assertRaises(LastSuperuser):
            self.supers.revoke("root", Account("root", is_superuser=True))
        self.assertIn("root", self.supers)

    def test_two_cannot_both_step_down(self):
        self.supers.revoke("ada", Account("root", is_superuser=True))
        with self.assertRaises(LastSuperuser):
            self.supers.revoke("ada", Account("ada", is_superuser=True))

    def test_nobody_else_can(self):
        with self.assertRaises(NotAllowed):
            self.supers.revoke("grace", Account("ada", is_superuser=True))

    def test_not_a_superuser(self):
        with self.assertRaises(SuperuserRuleError):
            self.supers.revoke("root", Account("grace"))

    def test_what_the_list_offers(self):
        self.assertTrue(self.supers.can_revoke("root", Account("ada", is_superuser=True)))
        self.assertFalse(self.supers.can_revoke("grace", Account("ada", is_superuser=True)))
        self.supers.revoke("root", Account("ada", is_superuser=True))
        self.assertFalse(self.supers.can_revoke("root", Account("root", is_superuser=True)))

    def test_losing_one_without_anyone_deciding(self):
        self.supers.ensure_can_lose("ada")
        self.supers.ensure_can_lose("not-a-superuser")
        self.supers.revoke("root", Account("ada", is_superuser=True))
        with self.assertRaises(LastSuperuser):
            self.supers.ensure_can_lose("root")
