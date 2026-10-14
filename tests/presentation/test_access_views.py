"""Gated access in the web layer: first-run setup, the signup hooks, the
pending person's page and the superuser review queue."""
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.application import access
from app.domain.models import AccessRequest
from app.presentation.auth_adapters import (
    PENDING_USER_SESSION_KEY,
    AccountAdapter,
    SocialAccountAdapter,
)

User = get_user_model()


@pytest.mark.django_db
@override_settings(FIRST_RUN_SETUP_ENABLED=True, GITGRIT_SETUP_TOKEN="tok-123")
class TestFirstRunSetup(TestCase):
    url = reverse("first_run_setup")

    def _post(self, **overrides):
        data = {
            "token": "tok-123",
            "email": "admin@example.com",
            "password1": "a-long-passphrase",
            "password2": "a-long-passphrase",
            **overrides,
        }
        return self.client.post(self.url, data)

    def test_every_page_goes_to_setup_while_there_are_no_users(self):
        response = self.client.get(reverse("home"))

        assert response.status_code == 302
        assert response.headers["Location"] == self.url

    def test_api_is_not_redirected(self):
        response = self.client.get("/api/v1/")
        assert response.status_code != 302

    def test_token_prefills_from_the_query_string(self):
        response = self.client.get(self.url + "?token=tok-123")
        assert b'value="tok-123"' in response.content

    def test_wrong_token_creates_nothing(self):
        response = self._post(token="guess")

        assert response.status_code == 200
        assert b"doesn&#x27;t match" in response.content
        assert not User.objects.exists()

    def test_mismatched_passwords_are_refused(self):
        response = self._post(password2="something-else")

        assert response.status_code == 200
        assert not User.objects.exists()

    def test_creates_admin_and_sends_them_to_create_the_first_workspace(self):
        response = self._post()

        assert response.status_code == 302
        assert response.headers["Location"] == reverse("create_tenant")
        admin = User.objects.get()
        assert admin.is_superuser
        assert self.client.session["_auth_user_id"] == str(admin.pk)

    def test_gone_once_done(self):
        baker.make("app.User")
        assert self.client.get(self.url).status_code == 404
        assert self._post().status_code == 404


def _request_with_session():
    request = RequestFactory().get("/")
    request.session = {}
    return request


@pytest.mark.django_db
class TestSignupAdapters(TestCase):
    def test_allauth_signup_form_is_closed_in_every_mode(self):
        # Password signup goes through the sign-in box instead.
        for mode in ("open", "approval", "onboarding"):
            with self.subTest(mode=mode), self.settings(SIGNUP_MODE=mode):
                response = self.client.get(reverse("account_signup"))
                self.assertTemplateUsed(response, "account/signup_closed.html")

    @override_settings(SIGNUP_MODE="approval")
    def test_gated_provider_signup_makes_an_inactive_user_with_a_request(self):
        adapter = SocialAccountAdapter()
        request = _request_with_session()
        assert adapter.is_open_for_signup(request, None)

        user = adapter.new_user(request, None)
        assert not user.is_active
        user.email, user.username = "new@example.com", "new"
        sociallogin = SimpleNamespace(user=user, save=lambda request: user.save())

        with mock.patch("app.tasks.send_email.defer"):
            adapter.save_user(request, sociallogin)

        assert AccessRequest.objects.get(user=user).is_pending

    @override_settings(SIGNUP_MODE="open")
    def test_open_provider_signup_is_active_without_a_request(self):
        adapter = SocialAccountAdapter()
        request = _request_with_session()

        user = adapter.new_user(request, None)
        user.email, user.username = "new@example.com", "new"
        sociallogin = SimpleNamespace(user=user, save=lambda request: user.save())
        adapter.save_user(request, sociallogin)

        assert user.is_active
        assert not AccessRequest.objects.filter(user=user).exists()

    def test_inactive_user_with_a_request_goes_to_their_request_page(self):
        user = baker.make("app.User", is_active=False)
        AccessRequest.objects.create(user=user)
        request = _request_with_session()

        response = AccountAdapter().respond_user_inactive(request, user)

        assert response.headers["Location"] == reverse("access_request_status")
        assert request.session[PENDING_USER_SESSION_KEY] == str(user.pk)

    def test_deactivated_user_without_a_request_gets_the_stock_page(self):
        user = baker.make("app.User", is_active=False)
        request = _request_with_session()

        response = AccountAdapter().respond_user_inactive(request, user)

        assert response.headers["Location"] == reverse("account_inactive")
        assert PENDING_USER_SESSION_KEY not in request.session


@pytest.mark.django_db
class TestAccessRequestStatus(TestCase):
    url = reverse("access_request_status")

    def setUp(self):
        self.user = baker.make("app.User", is_active=False, email="new@example.com")
        self.access_request = AccessRequest.objects.create(user=self.user)

    def _identify(self):
        session = self.client.session
        session[PENDING_USER_SESSION_KEY] = str(self.user.pk)
        session.save()

    def test_without_the_session_key_goes_to_login(self):
        response = self.client.get(self.url)
        assert response.headers["Location"] == reverse("account_login")

    @override_settings(SIGNUP_MODE="onboarding")
    def test_onboarding_asks_for_the_form_then_shows_pending(self):
        self._identify()
        assert b"Tell us about you" in self.client.get(self.url).content

        with mock.patch("app.tasks.send_email.defer"):
            response = self.client.post(
                self.url,
                {"name": "Ada", "company": "Acme", "role": "SRE", "goals": "CI"},
            )

        assert response.headers["Location"] == self.url
        self.access_request.refresh_from_db()
        assert self.access_request.answers["company"] == "Acme"
        assert b"on the list" in self.client.get(self.url).content

    @override_settings(SIGNUP_MODE="approval")
    def test_approval_mode_skips_the_form(self):
        self._identify()
        assert b"on the list" in self.client.get(self.url).content

    def test_rejected(self):
        self.access_request.status = AccessRequest.Status.REJECTED
        self.access_request.save()
        self._identify()
        assert b"Access not granted" in self.client.get(self.url).content


@pytest.mark.django_db
class TestReviewQueue(TestCase):
    url = reverse("access_request_list")

    def setUp(self):
        self.admin = baker.make("app.User", is_superuser=True)
        self.pending_user = baker.make(
            "app.User", is_active=False, email="new@example.com", username="new"
        )
        self.access_request = AccessRequest.objects.create(
            user=self.pending_user, answers={"name": "Ada", "company": "Acme"}
        )

    def test_superusers_only(self):
        self.client.force_login(baker.make("app.User"))
        assert self.client.get(self.url).status_code == 403
        approve = reverse("approve_access_request", args=[self.access_request.pk])
        assert self.client.post(approve).status_code == 403

    def test_lists_pending_requests(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        assert response.status_code == 200
        assert b"new@example.com" in response.content
        assert b"Acme" in response.content

    def _approve(self, **data):
        self.client.force_login(self.admin)
        url = reverse("approve_access_request", args=[self.access_request.pk])
        with mock.patch("app.tasks.send_email.defer"):
            return self.client.post(url, data)

    def test_approve_into_a_new_workspace(self):
        response = self._approve(workspace_mode="new", workspace_name="Acme", role="owner")

        assert response.headers["Location"] == self.url
        self.pending_user.refresh_from_db()
        assert self.pending_user.is_active
        membership = self.pending_user.memberships.get()
        assert (membership.tenant.name, membership.role) == ("Acme", "owner")

    def test_approve_into_an_existing_workspace(self):
        existing = baker.make("app.Tenant", name="Acme")

        self._approve(workspace_mode="existing", workspace_id=str(existing.pk), role="member")

        membership = self.pending_user.memberships.get()
        assert (membership.tenant, membership.role) == (existing, "member")

    def test_approve_without_a_workspace_changes_nothing(self):
        for data in (
            {"workspace_mode": "new", "workspace_name": " ", "role": "owner"},
            {"workspace_mode": "existing", "workspace_id": "nope", "role": "member"},
            {"workspace_mode": "new", "workspace_name": "Acme", "role": "god"},
        ):
            with self.subTest(data=data):
                self._approve(**data)
                self.access_request.refresh_from_db()
                assert self.access_request.is_pending

    def test_approve_dialog_lists_workspaces_and_prefills_the_company(self):
        baker.make("app.Tenant", name="Initech")
        self.client.force_login(self.admin)

        html = self.client.get(self.url).content.decode()

        assert 'name="workspace_name"' in html and 'value="Acme"' in html
        assert "Initech" in html
        # The role-sync script belongs in the page body, not in <title>.
        title = html[html.index("<title>"):html.index("</title>")]
        assert "<script" not in title
        assert "data-approve-form" in html.split("</title>", 1)[1]

    def test_reject(self):
        self.client.force_login(self.admin)
        url = reverse("reject_access_request", args=[self.access_request.pk])

        self.client.post(url)

        self.access_request.refresh_from_db()
        assert self.access_request.status == AccessRequest.Status.REJECTED

    def test_reviewing_twice_is_harmless(self):
        self.client.force_login(self.admin)
        with mock.patch("app.tasks.send_email.defer"):
            access.approve_access_request(
                self.access_request, self.admin, role="owner", new_workspace_name="Acme"
            )

        url = reverse("reject_access_request", args=[self.access_request.pk])
        self.client.post(url)

        self.access_request.refresh_from_db()
        assert self.access_request.status == AccessRequest.Status.APPROVED

    def test_get_is_not_allowed_to_review(self):
        self.client.force_login(self.admin)
        url = reverse("approve_access_request", args=[self.access_request.pk])
        assert self.client.get(url).status_code == 405


@pytest.mark.django_db
class TestSignInBox(TestCase):
    """One email + password box: a known email signs in, an unknown one signs
    up."""

    url = reverse("account_login")

    def _post(self, email="new@example.com", password="a-long-passphrase"):
        with mock.patch("app.tasks.send_email.defer"):
            return self.client.post(self.url, {"login": email, "password": password})

    @override_settings(SIGNUP_MODE="onboarding")
    def test_unknown_email_on_a_gated_deployment_becomes_a_pending_request(self):
        response = self._post()

        assert response.headers["Location"] == reverse("access_request_status")
        user = User.objects.get(email="new@example.com")
        assert not user.is_active
        assert user.check_password("a-long-passphrase")
        assert AccessRequest.objects.get(user=user).is_pending
        assert not user.memberships.exists()
        assert "_auth_user_id" not in self.client.session
        # The request page knows who they are and asks for the form.
        assert b"Tell us about you" in self.client.get(response.headers["Location"]).content

    @override_settings(SIGNUP_MODE="open")
    def test_unknown_email_on_an_open_deployment_is_signed_in_without_a_workspace(self):
        response = self._post()

        user = User.objects.get(email="new@example.com")
        assert user.is_active
        assert self.client.session["_auth_user_id"] == str(user.pk)
        # Workspaces are handed out by admins, even on an open deployment.
        assert not user.memberships.exists()
        assert self.client.get(response.headers["Location"]).headers["Location"] == reverse("no_workspace")

    @override_settings(SIGNUP_MODE="approval")
    def test_weak_password_creates_nothing(self):
        response = self._post(password="123")

        assert response.status_code == 200
        assert b"too short" in response.content
        assert not User.objects.exists()

    @override_settings(SIGNUP_MODE="approval")
    def test_known_email_signs_in(self):
        user = baker.make("app.User", email="ada@example.com")
        user.set_password("a-long-passphrase")
        user.save()

        response = self._post(email="ada@example.com")

        assert response.status_code == 302
        assert self.client.session["_auth_user_id"] == str(user.pk)
        assert User.objects.count() == 1

    @override_settings(SIGNUP_MODE="approval")
    def test_known_email_wrong_password_is_refused_not_signed_up(self):
        user = baker.make("app.User", email="ada@example.com")
        user.set_password("a-long-passphrase")
        user.save()

        response = self._post(email="ada@example.com", password="not-the-password")

        assert response.status_code == 200
        assert "_auth_user_id" not in self.client.session
        assert User.objects.count() == 1

    @override_settings(SIGNUP_MODE="approval")
    def test_pending_password_user_lands_on_their_request_page(self):
        self._post()
        self.client.session.flush()

        response = self._post()

        assert response.headers["Location"] == reverse("access_request_status")
        assert User.objects.count() == 1

    def test_provider_only_account_is_told_to_use_its_provider(self):
        user = baker.make("app.User", email="ada@example.com")
        user.set_unusable_password()
        user.save()

        response = self._post(email="ada@example.com")

        assert response.status_code == 200
        assert b"signs in with a provider" in response.content
        assert User.objects.count() == 1
