"""A workspace always has an owner: roles change and people leave only in
ways that keep one, and only owners make or unmake owners."""
from unittest import mock

import pytest
from django.db import transaction
from django.test import TestCase
from model_bakery import baker

from app.application import membership_service as ms
from app.domain.models import Membership, Tenant


def _member(tenant, role):
    return baker.make("app.Membership", tenant=tenant, role=role)


@pytest.mark.django_db
class TestChangeRole(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = _member(self.tenant, "owner")
        self.admin = _member(self.tenant, "admin")
        self.member = _member(self.tenant, "member")

    def test_owner_makes_another_owner_and_it_is_announced(self):
        with mock.patch("app.application.membership_service.publish") as publish:
            ms.change_role(self.member, "owner", self.owner.user)

        self.member.refresh_from_db()
        assert self.member.role == "owner"
        event = publish.call_args.args[0]
        assert (event.old_role, event.new_role) == ("member", "owner")
        assert event.changed_by_user_id == str(self.owner.user_id)

    def test_admin_manages_admins_and_members_but_not_owners(self):
        ms.change_role(self.member, "admin", self.admin.user)
        assert Membership.objects.get(pk=self.member.pk).role == "admin"

        with pytest.raises(ms.NotAllowed):
            ms.change_role(self.member, "owner", self.admin.user)
        with pytest.raises(ms.NotAllowed):
            ms.change_role(self.owner, "member", self.admin.user)

    def test_member_changes_nothing(self):
        with pytest.raises(ms.NotAllowed):
            ms.change_role(self.admin, "member", self.member.user)

    def test_superuser_counts_as_owner(self):
        root = baker.make("app.User", is_superuser=True)
        ms.change_role(self.member, "owner", root)
        assert Membership.objects.get(pk=self.member.pk).role == "owner"

    def test_last_owner_cannot_step_down(self):
        with pytest.raises(ms.LastOwnerError):
            ms.change_role(self.owner, "admin", self.owner.user)
        assert Membership.objects.get(pk=self.owner.pk).role == "owner"

    def test_an_owner_steps_down_once_another_exists(self):
        ms.change_role(self.admin, "owner", self.owner.user)
        ms.change_role(self.owner, "member", self.owner.user)
        assert Membership.objects.get(pk=self.owner.pk).role == "member"

    def test_unknown_role(self):
        with pytest.raises(ValueError):
            ms.change_role(self.member, "god", self.owner.user)


@pytest.mark.django_db
class TestRemoveMember(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.owner = _member(self.tenant, "owner")
        self.admin = _member(self.tenant, "admin")

    def test_admin_removes_members_but_not_owners(self):
        member = _member(self.tenant, "member")
        ms.remove_member(member, self.admin.user)
        assert not Membership.objects.filter(pk=member.pk).exists()

        _member(self.tenant, "owner")
        with pytest.raises(ms.NotAllowed):
            ms.remove_member(self.owner, self.admin.user)

    def test_owner_removes_another_owner_but_never_the_last(self):
        second = _member(self.tenant, "owner")
        ms.remove_member(second, self.owner.user)
        assert not Membership.objects.filter(pk=second.pk).exists()

        with pytest.raises(ms.LastOwnerError):
            ms.remove_member(self.owner, self.owner.user)

    def test_anyone_but_the_last_owner_can_leave(self):
        ms.remove_member(self.admin, self.admin.user)
        assert not Membership.objects.filter(pk=self.admin.pk).exists()


@pytest.mark.django_db
class TestGuardOutsideTheService(TestCase):
    """The Django admin and user deletion don't go through the service."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = _member(self.tenant, "owner")

    def test_deleting_the_last_owner_directly_is_refused(self):
        # A refused delete poisons its transaction, as any failed write does.
        with pytest.raises(ms.LastOwnerError), transaction.atomic():
            self.owner.delete()
        with pytest.raises(ms.LastOwnerError), transaction.atomic():
            Membership.objects.filter(pk=self.owner.pk).delete()
        assert Membership.objects.filter(pk=self.owner.pk).exists()

    def test_demoting_the_last_owner_directly_is_refused(self):
        self.owner.role = "member"
        with pytest.raises(ms.LastOwnerError):
            self.owner.save()

    def test_deleting_a_user_who_is_the_last_owner_is_refused(self):
        with pytest.raises(ms.LastOwnerError):
            self.owner.user.delete()

    def test_deleting_the_workspace_takes_its_owners_with_it(self):
        self.tenant.delete()
        assert not Membership.objects.filter(pk=self.owner.pk).exists()

        other = baker.make("app.Tenant")
        _member(other, "owner")
        Tenant.objects.filter(pk=other.pk).delete()
        assert not Tenant.objects.filter(pk=other.pk).exists()
