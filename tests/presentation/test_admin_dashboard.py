"""The admin dashboard: settings-style sections for superusers, with the
access-request queue and the superusers themselves."""
import json

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AccessRequest, User

HTMX = {"HTTP_HX_REQUEST": "true"}


def _toast(response):
    return json.loads(response["HX-Trigger"])["toast"]


@pytest.mark.django_db
class TestDashboard(TestCase):
    url = reverse("admin_dashboard")

    def setUp(self):
        self.root = baker.make("app.User", is_superuser=True, is_staff=True, email="root@example.com")
        self.client.force_login(self.root)

    def test_superusers_only(self):
        self.client.force_login(baker.make("app.User"))
        assert self.client.get(self.url).status_code == 403
        assert self.client.get(reverse("access_request_tab")).status_code == 403

    def test_sections(self):
        html = self.client.get(self.url).content.decode()

        for section in ("section-access-requests", "section-superusers"):
            assert f'id="{section}"' in html
            assert f'href="#{section}" data-settings-link' in html

    def test_the_old_queue_address_opens_its_tab(self):
        response = self.client.get(reverse("access_request_list") + "?status=rejected")
        assert response.headers["Location"] == self.url + "?status=rejected#section-access-requests"

    def test_status_tabs_swap_in_place(self):
        baker.make(AccessRequest, user__email="gone@example.com", status="rejected")

        response = self.client.get(reverse("access_request_tab") + "?status=rejected", **HTMX)

        html = response.content.decode()
        assert 'id="access-requests-section"' in html
        assert "gone@example.com" in html
        assert "<html" not in html

    def test_navbar_links_here(self):
        assert f'href="{self.url}"' in self.client.get(self.url).content.decode()


@pytest.mark.django_db
class TestSuperusers(TestCase):
    url = reverse("admin_dashboard")

    def setUp(self):
        self.root = baker.make("app.User", is_superuser=True, is_staff=True, email="root@example.com")
        self.client.force_login(self.root)

    def _grant(self, email, **extra):
        return self.client.post(reverse("grant_superuser"), {"email": email}, **extra)

    def _revoke(self, user, **extra):
        return self.client.post(reverse("revoke_superuser", args=[user.pk]), **extra)

    def test_the_only_superuser_cannot_be_removed(self):
        html = self.client.get(self.url).content.decode()

        assert "The only one" in html
        assert reverse("revoke_superuser", args=[self.root.pk]) not in html

    def test_grant(self):
        ada = baker.make("app.User", email="ada@example.com")

        response = self._grant("ADA@example.com", **HTMX)

        ada.refresh_from_db()
        assert ada.is_superuser and ada.is_staff
        assert ada.superuser_granted_by == self.root
        assert _toast(response)["text"] == "ada@example.com is now a superuser."
        assert 'data-superuser="ada@example.com"' in response.content.decode()

    def test_grant_asks_for_confirmation(self):
        html = self.client.get(self.url).content.decode()
        assert 'hx-confirm="Make {email} a superuser?"' in html

    def test_grant_refusals_keep_what_was_typed(self):
        baker.make("app.User", email="pending@example.com", is_active=False)
        for email in ("ghost@example.com", "pending@example.com", "root@example.com"):
            with self.subTest(email=email):
                response = self._grant(email, **HTMX)
                assert _toast(response)["level"] == "error"
                assert f'value="{email}"' in response.content.decode()
        assert User.objects.filter(is_superuser=True).count() == 1

    def test_revoke_another(self):
        ada = baker.make("app.User", email="ada@example.com", is_superuser=True, is_staff=True)

        response = self._revoke(ada, **HTMX)

        ada.refresh_from_db()
        assert not ada.is_superuser and not ada.is_staff
        assert 'data-superuser="ada@example.com"' not in response.content.decode()

    def test_stepping_down_navigates_away(self):
        baker.make("app.User", is_superuser=True)

        response = self._revoke(self.root, **HTMX)

        assert response["HX-Redirect"] == reverse("dashboard")
        self.root.refresh_from_db()
        assert not self.root.is_superuser

    def test_the_last_one_stays(self):
        response = self._revoke(self.root, **HTMX)

        assert _toast(response)["level"] == "error"
        self.root.refresh_from_db()
        assert self.root.is_superuser

    def test_non_superusers_cannot(self):
        member = baker.make("app.User")
        self.client.force_login(member)

        assert self._grant(member.email).status_code == 403
        assert self._revoke(self.root).status_code == 403
        member.refresh_from_db()
        assert not member.is_superuser
