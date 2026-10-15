"""Workspace changes made in the app reach the notification center, end to end
through the real event bus: the person who made the change is not told, the
other admins are."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application import invitations
from app.application.notifications.dispatcher import dispatch
from app.application.standard_runs import expire_stale_runs
from app.domain.models import (
    InboxItem,
    Notification,
    StandardExecution,
    WorkspaceInvitation,
)
from tests.support import deliver_defer_patch


class WorkspaceChangeNotificationTests(TestCase):
    def setUp(self):
        patch = deliver_defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.tenant = baker.make("app.Tenant")
        self.me = baker.make("app.User", first_name="Dana", last_name="Lee")
        self.other_admin = baker.make("app.User")
        baker.make("app.Membership", user=self.me, tenant=self.tenant, role="owner")
        baker.make("app.Membership", user=self.other_admin, tenant=self.tenant, role="admin")
        self.client.force_login(self.me)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _delivered_to(self, notification):
        dispatch(str(notification.pk))
        return set(
            InboxItem.objects.filter(notification=notification).values_list("recipient_id", flat=True)
        )

    def test_removing_a_project_tells_the_other_admins(self):
        project = baker.make("app.Project", tenant=self.tenant, name="Old repo", webhook_id="")

        self.client.post(reverse("delete_project", args=[project.pk]))

        n = Notification.objects.get(kind="project.removed")
        self.assertEqual(n.body, "Dana Lee removed Old repo.")
        self.assertEqual(self._delivered_to(n), {self.other_admin.pk})

    def test_adding_a_member_tells_the_other_admins(self):
        newcomer = baker.make("app.User", email="sam@example.test", first_name="Sam", last_name="Kim")

        with mock.patch("app.tasks.send_email.defer"):
            self.client.post(reverse("invite_member"), {"email": "sam@example.test", "role": "member"})
        # Nobody joins on someone else's say-so: Sam accepts the invitation.
        assert not Notification.objects.filter(kind="member.joined").exists()
        invitations.accept(WorkspaceInvitation.objects.get(email="sam@example.test"), newcomer, via_link=True)

        n = Notification.objects.get(kind="member.joined")
        self.assertEqual(n.body, "Dana Lee added Sam Kim as member.")
        self.assertEqual(self._delivered_to(n), {self.other_admin.pk})
        self.assertNotIn(newcomer.pk, self._delivered_to(n))

    def test_removing_a_member_tells_the_other_admins(self):
        leaver = baker.make("app.User", first_name="Sam", last_name="Kim")
        membership = baker.make("app.Membership", user=leaver, tenant=self.tenant, role="member")

        self.client.post(reverse("remove_member", args=[membership.pk]))

        n = Notification.objects.get(kind="member.removed")
        self.assertEqual(n.body, "Dana Lee removed Sam Kim.")
        self.assertEqual(self._delivered_to(n), {self.other_admin.pk})

    def test_leaving_tells_the_admins_who_stay(self):
        leaver = baker.make("app.User", first_name="Sam", last_name="Kim")
        baker.make("app.Membership", user=leaver, tenant=self.tenant, role="member")
        self.client.force_login(leaver)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

        self.client.post(reverse("leave_workspace"))

        n = Notification.objects.get(kind="member.removed")
        self.assertEqual((n.title, n.body), ("Member left", "Sam Kim left the workspace."))
        self.assertEqual(self._delivered_to(n), {self.me.pk, self.other_admin.pk})

    def test_activating_a_standard_tells_the_other_admins(self):
        standard = baker.make("app.Standard", tenant=self.tenant, name="Pinned CI", enabled=False, draft=False)

        with mock.patch("app.application.standard_runs.run_standards.configure"):
            self.client.post(reverse("toggle_standard", args=[standard.pk]))

        n = Notification.objects.get(kind="standard.changed")
        self.assertEqual(n.title, "Standard activated")
        self.assertEqual(self._delivered_to(n), {self.other_admin.pk})


class TimedOutRunNotificationTests(TestCase):
    @override_settings(STANDARD_RUN_STALE_MINUTES=30)
    def test_expiring_stale_runs_raises_one_per_project(self):
        tenant = baker.make("app.Tenant")
        projects = baker.make("app.Project", tenant=tenant, _quantity=2)
        for project in projects:
            standard = baker.make("app.Standard", tenant=tenant)
            row = baker.make(
                "app.StandardExecution", project=project, standard=standard,
                standard_name=standard.name, event_type="manual",
                status=StandardExecution.Status.RUNNING,
            )
            StandardExecution.objects.filter(pk=row.pk).update(
                created_at=timezone.now() - timedelta(minutes=31)
            )

        with deliver_defer_patch():
            self.assertEqual(expire_stale_runs(), 2)

        self.assertEqual(
            sorted(Notification.objects.filter(kind="run.timed_out").values_list("context__project_id", flat=True)),
            sorted(str(p.pk) for p in projects),
        )
