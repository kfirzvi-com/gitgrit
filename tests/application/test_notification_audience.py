"""Audience resolution must never leak a notice outside its workspace."""

from django.test import TestCase
from model_bakery import baker

from app.application.notifications.audience import resolve
from app.domain.notifications import Audience


class ResolveTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.users = {}
        for role in ("owner", "admin", "member"):
            user = baker.make("app.User")
            baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
            self.users[role] = str(user.pk)

    def _resolve(self, audience, **kwargs):
        return resolve(audience, str(self.tenant.pk), **kwargs)

    def test_admins_excludes_members(self):
        self.assertEqual(
            set(self._resolve(Audience.admins())),
            {self.users["owner"], self.users["admin"]},
        )

    def test_team_includes_all_three_roles(self):
        self.assertEqual(
            set(self._resolve(Audience.team())), set(self.users.values())
        )

    def test_user_in_another_tenant_is_excluded_even_when_named(self):
        outsider = baker.make("app.User")
        baker.make("app.Membership", user=outsider, tenant=baker.make("app.Tenant"))

        result = self._resolve(Audience.users(str(outsider.pk)))

        self.assertEqual(result, [])

    def test_mentioned_members_are_included(self):
        result = self._resolve(
            Audience.admins(), mentioned_user_ids=(self.users["member"],)
        )

        self.assertIn(self.users["member"], result)

    def test_mentioned_non_member_is_dropped(self):
        outsider = baker.make("app.User")

        result = self._resolve(Audience.admins(), mentioned_user_ids=(str(outsider.pk),))

        self.assertNotIn(str(outsider.pk), result)

    def test_result_is_distinct(self):
        result = self._resolve(
            Audience.admins(),
            mentioned_user_ids=(self.users["admin"], self.users["admin"]),
        )

        self.assertEqual(len(result), len(set(result)))
        self.assertEqual(len(result), 2)
