"""The superuser service stores the domain's decisions (tests in
tests/domain/test_superusers.py) and the backstop holds outside it."""
from unittest import mock

import pytest
from django.db import transaction
from django.test import TestCase
from model_bakery import baker

from app.application import superuser_service
from app.domain.events import SuperuserGranted, SuperuserRevoked
from app.domain.superusers import LastSuperuser, NotAllowed


def _publish():
    return mock.patch("app.application.superuser_service.publish")


@pytest.mark.django_db
class TestService(TestCase):
    def setUp(self):
        self.root = baker.make("app.User", is_superuser=True, is_staff=True)

    def test_grant_stores_who_and_when_and_publishes(self):
        ada = baker.make("app.User")
        with _publish() as publish:
            superuser_service.grant(ada, self.root)

        ada.refresh_from_db()
        assert (ada.is_superuser, ada.is_staff, ada.superuser_granted_by) == (True, True, self.root)
        assert ada.superuser_granted_at is not None
        assert publish.call_args.args[0] == SuperuserGranted(str(ada.pk), str(self.root.pk))

    def test_revoke_clears_it_and_publishes(self):
        ada = baker.make("app.User", is_superuser=True, is_staff=True)
        with _publish() as publish:
            superuser_service.revoke(ada, self.root)

        ada.refresh_from_db()
        assert (ada.is_superuser, ada.is_staff, ada.superuser_granted_at) == (False, False, None)
        assert publish.call_args.args[0] == SuperuserRevoked(str(ada.pk), str(self.root.pk))

    def test_a_refusal_stores_nothing(self):
        ada = baker.make("app.User")
        with _publish() as publish, pytest.raises(NotAllowed):
            superuser_service.grant(baker.make("app.User"), ada)
        publish.assert_not_called()

    def test_an_inactive_superuser_does_not_count(self):
        baker.make("app.User", is_superuser=True, is_active=False)
        with pytest.raises(LastSuperuser):
            superuser_service.revoke(self.root, self.root)


@pytest.mark.django_db
class TestBackstop(TestCase):
    """The Django admin doesn't go through the service."""

    def setUp(self):
        self.root = baker.make("app.User", is_superuser=True, is_staff=True)

    def test_unticking_the_last_superuser_is_refused(self):
        self.root.is_superuser = False
        with pytest.raises(LastSuperuser), transaction.atomic():
            self.root.save()

    def test_deactivating_the_last_superuser_is_refused(self):
        self.root.is_active = False
        with pytest.raises(LastSuperuser), transaction.atomic():
            self.root.save()

    def test_deleting_the_last_superuser_is_refused(self):
        with pytest.raises(LastSuperuser), transaction.atomic():
            self.root.delete()

    def test_with_another_superuser_it_is_fine(self):
        baker.make("app.User", is_superuser=True)
        self.root.is_superuser = False
        self.root.save()

    def test_ordinary_saves_are_untouched(self):
        self.root.save(update_fields=["last_login"])
        user = baker.make("app.User")
        user.first_name = "Ada"
        user.save()
