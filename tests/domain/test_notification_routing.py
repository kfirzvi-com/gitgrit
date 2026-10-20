"""Notification routing: who hears each kind, and never anyone outside the workspace."""
from django.test import TestCase
from model_bakery import baker

from app.domain.notifications.notification_routing import (
    FALLBACK,
    ROUTES,
    Admins,
    Route,
    Team,
    Triggerer,
    route_for,
)
from app.domain.models import Notification, User


class RoutingTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.users = {}
        for role in ("owner", "admin", "member"):
            user = baker.make("app.User")
            baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
            self.users[role] = str(user.pk)

    def _notification(self, triggered_by=()):
        return Notification.could_not_evaluate(
            project=self.project, error="boom", triggered_by_user_ids=triggered_by
        )

    def test_run_problems_go_to_admins_and_the_triggerer_on_the_inbox(self):
        for kind in (
            "run.failed", "standards.failing", "project.critical", "run.timed_out",
            "connection.broken", "graph.failed",
        ):
            with self.subTest(kind=kind):
                route = route_for(kind)
                self.assertIs(route, ROUTES[kind])
                self.assertEqual([type(a) for a in route.audience], [Admins, Triggerer])
                self.assertEqual(route.channels, ("inbox",))

    def test_could_not_verify_goes_to_every_member_on_the_inbox(self):
        """Audience is every member: owner, admin and member all hear it; a
        member of another workspace does not."""
        outsider = baker.make("app.User")
        baker.make("app.Membership", user=outsider, tenant=baker.make("app.Tenant"), role="owner")
        route = route_for("grade.unverified")
        self.assertIs(route, ROUTES["grade.unverified"])
        self.assertEqual([type(a) for a in route.audience], [Team])
        self.assertEqual(route.channels, ("inbox",))
        n = Notification.grade_unverified(
            project=self.project, standard_names=["No secrets"], standard_ids=["s1"], branch="main"
        )
        self.assertEqual(route.recipients(n), sorted(self.users.values()))

    def test_unknown_kind_falls_back_to_admins_on_the_inbox_and_warns(self):
        with self.assertLogs("app.domain.notifications.notification_routing", "WARNING"):
            self.assertIs(route_for("nope"), FALLBACK)
        self.assertEqual([type(a) for a in FALLBACK.audience], [Admins])

    def test_admins_are_owners_and_admins(self):
        self.assertEqual(
            Admins().user_ids(self._notification()), {self.users["owner"], self.users["admin"]}
        )

    def test_team_is_everyone(self):
        self.assertEqual(Team().user_ids(self._notification()), set(self.users.values()))

    def test_the_triggerer_is_added_when_a_member(self):
        route = route_for("run.failed")
        recipients = route.recipients(self._notification(triggered_by=[self.users["member"]]))
        self.assertEqual(set(recipients), set(self.users.values()))

    def test_a_triggerer_outside_the_workspace_is_dropped(self):
        outsider = baker.make("app.User")
        baker.make("app.Membership", user=outsider, tenant=baker.make("app.Tenant"))
        n = self._notification(triggered_by=[str(outsider.pk)])
        self.assertEqual(Triggerer().user_ids(n), set())

    def test_no_triggerer_means_nobody_extra(self):
        self.assertEqual(Triggerer().user_ids(self._notification()), set())

    def test_recipients_are_distinct_and_sorted(self):
        route = Route((Admins(), Team()), ("inbox",))
        recipients = route.recipients(self._notification())
        self.assertEqual(recipients, sorted(set(self.users.values())))

    def test_workspace_changes_go_to_admins_on_the_inbox(self):
        for kind in (
            "ai_provider.failed", "project.added", "project.removed", "member.joined",
            "member.removed", "standard.changed",
        ):
            with self.subTest(kind=kind):
                route = route_for(kind)
                self.assertEqual([type(a) for a in route.audience], [Admins])
                self.assertEqual(route.channels, ("inbox",))

    def test_nobody_is_told_about_their_own_change(self):
        actor = baker.make("app.User")
        baker.make("app.Membership", user=actor, tenant=self.tenant, role="admin")
        n = Notification.project_added(project=self.project, actor=actor)

        recipients = route_for(n.kind).recipients(n)

        self.assertNotIn(str(actor.pk), recipients)
        self.assertEqual(set(recipients), {self.users["owner"], self.users["admin"]})

    def test_a_role_change_also_tells_the_member_it_is_about(self):
        actor = baker.make("app.User")
        baker.make("app.Membership", user=actor, tenant=self.tenant, role="owner")
        n = Notification.member_role_changed(
            tenant_id=self.tenant.pk,
            member=User.objects.get(pk=self.users["member"]),
            old_role="member",
            new_role="admin",
            actor=actor,
        )

        recipients = route_for(n.kind).recipients(n)

        self.assertEqual(set(recipients), set(self.users.values()))
        self.assertNotIn(str(actor.pk), recipients)
