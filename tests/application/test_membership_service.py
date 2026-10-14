"""The membership service applies the roster's decisions to storage and
publishes them. The rules themselves are tested in
tests/domain/test_workspace_roles.py; here: rows change only when the domain
says yes, events go out, and the backstop holds outside the service."""
from unittest import mock

import pytest
from django.db import transaction
from django.test import TestCase
from model_bakery import baker

from app.application import membership_service as ms
from app.domain.events import MemberJoined, MemberRemoved, MemberRoleChanged
from app.domain.models import Membership, Tenant
from app.domain.workspace_roles import LastOwner, NotAllowed


def _member(tenant, role):
    return baker.make("app.Membership", tenant=tenant, role=role)


def _publish():
    return mock.patch("app.application.membership_service.publish")


@pytest.mark.django_db
class TestService(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = _member(self.tenant, "owner")
        self.member = _member(self.tenant, "member")

    def test_change_role_stores_and_publishes(self):
        with _publish() as publish:
            ms.change_role(self.member, "admin", self.owner.user)

        assert Membership.objects.get(pk=self.member.pk).role == "admin"
        assert isinstance(publish.call_args.args[0], MemberRoleChanged)

    def test_a_refusal_stores_and_publishes_nothing(self):
        with _publish() as publish, pytest.raises(NotAllowed):
            ms.change_role(self.owner, "member", self.member.user)

        assert Membership.objects.get(pk=self.owner.pk).role == "owner"
        publish.assert_not_called()

    def test_the_same_role_publishes_nothing(self):
        with _publish() as publish:
            ms.change_role(self.member, "member", self.owner.user)
        publish.assert_not_called()

    def test_decides_on_the_stored_role_not_a_stale_copy(self):
        stale = Membership.objects.get(pk=self.owner.pk)
        second = _member(self.tenant, "owner")
        ms.change_role(second, "member", self.owner.user)

        stale.role = "owner"
        with pytest.raises(LastOwner):
            ms.change_role(stale, "member", self.owner.user)

    def test_add_member(self):
        newcomer = baker.make("app.User")
        with _publish() as publish:
            ms.add_member(self.tenant, newcomer, "admin", by=self.owner.user)

        assert Membership.objects.get(user=newcomer, tenant=self.tenant).role == "admin"
        assert isinstance(publish.call_args.args[0], MemberJoined)

    def test_remove_member(self):
        with _publish() as publish:
            ms.remove_member(self.member, self.owner.user)

        assert not Membership.objects.filter(pk=self.member.pk).exists()
        assert isinstance(publish.call_args.args[0], MemberRemoved)

    def test_the_last_owner_stays(self):
        with pytest.raises(LastOwner):
            ms.remove_member(self.owner, self.owner.user)
        assert Membership.objects.filter(pk=self.owner.pk).exists()


@pytest.mark.django_db
class TestBackstop(TestCase):
    """The Django admin and user deletion don't go through the service."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = _member(self.tenant, "owner")

    def test_deleting_the_last_owner_directly_is_refused(self):
        # A refused delete poisons its transaction, as any failed write does.
        with pytest.raises(LastOwner), transaction.atomic():
            self.owner.delete()
        with pytest.raises(LastOwner), transaction.atomic():
            Membership.objects.filter(pk=self.owner.pk).delete()
        assert Membership.objects.filter(pk=self.owner.pk).exists()

    def test_demoting_the_last_owner_directly_is_refused(self):
        self.owner.role = "member"
        with pytest.raises(LastOwner):
            self.owner.save()

    def test_deleting_a_user_who_is_the_last_owner_is_refused(self):
        with pytest.raises(LastOwner):
            self.owner.user.delete()

    def test_deleting_the_workspace_takes_its_owners_with_it(self):
        self.tenant.delete()
        assert not Membership.objects.filter(pk=self.owner.pk).exists()

        other = baker.make("app.Tenant")
        _member(other, "owner")
        Tenant.objects.filter(pk=other.pk).delete()
        assert not Tenant.objects.filter(pk=other.pk).exists()
