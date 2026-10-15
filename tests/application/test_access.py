"""Gated access: first-run setup, access requests and their review.

A gated signup is an inactive user with a pending request. Approval is the
one place they become active and get a workspace; superusers hear about new
requests by email, and so does the person once they are approved.
"""
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from model_bakery import baker

from app.application import access
from app.domain.models import AccessRequest, Membership
from app.domain.workspace_roles import MembershipRuleError
from app.infrastructure.mailer import send_templated


def _send_email_patch():
    return mock.patch("app.tasks.send_email.defer")


@pytest.mark.django_db
class TestFirstAdmin(TestCase):
    def test_creates_superuser_with_verified_email_and_no_workspace(self):
        user = access.create_first_admin("admin@example.com", "a-long-passphrase")

        assert user.is_superuser and user.is_staff and user.is_active
        assert user.check_password("a-long-passphrase")
        assert EmailAddress.objects.get(user=user).verified
        # Workspaces are created deliberately, not handed out on signup.
        assert not Membership.objects.filter(user=user).exists()

    def test_refuses_once_any_user_exists(self):
        baker.make("app.User")

        with pytest.raises(access.SetupAlreadyDone):
            access.create_first_admin("admin@example.com", "a-long-passphrase")

    @override_settings(FIRST_RUN_SETUP_ENABLED=True)
    def test_setup_required_only_while_there_are_no_users(self):
        assert access.setup_required()
        baker.make("app.User")
        assert not access.setup_required()


class TestSetupToken(TestCase):
    @override_settings(SECRET_KEY="one", GITGRIT_SETUP_TOKEN="")
    def test_derived_from_secret_key_and_stable(self):
        token = access.setup_token()
        assert token == access.setup_token()
        assert access.setup_token_matches(f"  {token} ")
        with override_settings(SECRET_KEY="two"):
            assert access.setup_token() != token

    @override_settings(GITGRIT_SETUP_TOKEN="chosen-token")
    def test_explicit_token_wins(self):
        assert access.setup_token() == "chosen-token"
        assert not access.setup_token_matches("")


@pytest.mark.django_db
class TestRegisterWithPassword(TestCase):
    @override_settings(SIGNUP_MODE="approval")
    def test_gated_signup_is_inactive_with_an_unverified_email(self):
        with _send_email_patch():
            user = access.register_with_password("new@example.com", "a-long-passphrase")

        assert not user.is_active
        assert user.check_password("a-long-passphrase")
        assert AccessRequest.objects.get(user=user).is_pending
        assert not EmailAddress.objects.get(user=user).verified

    @override_settings(SIGNUP_MODE="open")
    def test_open_signup_is_active_without_a_request(self):
        user = access.register_with_password("new@example.com", "a-long-passphrase")

        assert user.is_active
        assert not AccessRequest.objects.filter(user=user).exists()


@pytest.mark.django_db
class TestOpenAccessRequest(TestCase):
    @override_settings(SIGNUP_MODE="approval")
    def test_approval_mode_emails_superusers_at_once(self):
        baker.make("app.User", is_superuser=True, email="boss@example.com")
        baker.make("app.User", is_superuser=True, is_active=False, email="gone@example.com")
        user = baker.make("app.User", is_active=False, email="new@example.com")

        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access.open_access_request(user)

        defer.assert_called_once()
        kwargs = defer.call_args.kwargs
        assert kwargs["template"] == "access_requested"
        assert kwargs["to"] == ["boss@example.com"]
        assert kwargs["context"]["email"] == "new@example.com"

    @override_settings(SIGNUP_MODE="onboarding")
    def test_onboarding_mode_waits_for_the_form(self):
        baker.make("app.User", is_superuser=True, email="boss@example.com")
        user = baker.make("app.User", is_active=False)

        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access_request = access.open_access_request(user)
        defer.assert_not_called()

        answers = {"name": "Ada", "company": "Acme", "role": "SRE", "goals": "CI"}
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access.submit_access_request(access_request, answers)

        access_request.refresh_from_db()
        assert access_request.answers == answers
        assert access_request.is_submitted
        assert defer.call_args.kwargs["context"]["answers"] == answers


@pytest.mark.django_db
class TestEmailConfirmation(TestCase):
    """A password sign-up reaches superusers once its email is confirmed."""

    def setUp(self):
        baker.make("app.User", is_superuser=True, email="boss@example.com")

    def _sign_up(self):
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            user = access.register_with_password("new@example.com", "a-long-passphrase")
        return user, defer

    def _confirm(self, user):
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access.confirm_access_request_email(user)
        return defer

    @override_settings(SIGNUP_MODE="approval")
    def test_unconfirmed_is_silent_and_out_of_the_count(self):
        user, defer = self._sign_up()

        defer.assert_not_called()
        assert not AccessRequest.objects.get(user=user).is_email_confirmed
        assert access.pending_access_request_count() == 0

    @override_settings(SIGNUP_MODE="approval")
    def test_confirming_tells_superusers_once(self):
        user, _ = self._sign_up()

        defer = self._confirm(user)
        assert defer.call_args.kwargs["to"] == ["boss@example.com"]
        assert access.pending_access_request_count() == 1
        self._confirm(user).assert_not_called()

    @override_settings(SIGNUP_MODE="onboarding")
    def test_with_the_form_on_they_hear_once_the_form_is_in(self):
        user, _ = self._sign_up()
        self._confirm(user).assert_not_called()

        request = AccessRequest.objects.get(user=user)
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access.submit_access_request(request, {"name": "Ada"})
        defer.assert_called_once()

    @override_settings(SIGNUP_MODE="approval")
    def test_a_provider_signup_is_confirmed_from_the_start(self):
        user = baker.make("app.User", is_active=False)
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            request = access.open_access_request(user)
        assert request.is_email_confirmed
        defer.assert_called_once()


@pytest.mark.django_db
class TestReview(TestCase):
    def setUp(self):
        self.reviewer = baker.make("app.User", is_superuser=True)
        self.user = baker.make(
            "app.User", is_active=False, username="ada", email="ada@example.com"
        )
        self.access_request = AccessRequest.objects.create(
            user=self.user, answers={"name": "Ada"}, email_confirmed_at=timezone.now()
        )

    def _approve(self, **kwargs):
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            workspace = access.approve_access_request(
                self.access_request, self.reviewer, **kwargs
            )
        return workspace, defer

    def test_approve_into_a_new_workspace(self):
        workspace, defer = self._approve(role="owner", new_workspace_name=" Acme ")

        self.user.refresh_from_db()
        self.access_request.refresh_from_db()
        assert self.user.is_active
        assert self.access_request.status == AccessRequest.Status.APPROVED
        assert self.access_request.reviewed_by == self.reviewer
        assert workspace.name == "Acme"
        assert Membership.objects.get(user=self.user).tenant == workspace
        assert Membership.objects.get(user=self.user).role == "owner"
        kwargs = defer.call_args.kwargs
        assert kwargs["template"] == "access_approved"
        assert kwargs["to"] == ["ada@example.com"]
        assert kwargs["context"]["name"] == "Ada"
        assert kwargs["context"]["workspace"] == "Acme"

    def test_approve_into_an_existing_workspace(self):
        existing = baker.make("app.Tenant", name="Acme")

        workspace, _ = self._approve(role="member", workspace=existing)

        assert workspace == existing
        membership = Membership.objects.get(user=self.user)
        assert (membership.tenant, membership.role) == (existing, "member")

    def test_approve_needs_exactly_one_workspace_choice(self):
        existing = baker.make("app.Tenant")
        for kwargs in ({}, {"workspace": existing, "new_workspace_name": "Acme"}, {"new_workspace_name": "  "}):
            with self.subTest(kwargs=kwargs), pytest.raises(ValueError):
                access.approve_access_request(
                    self.access_request, self.reviewer, role="member", **kwargs
                )
        self.access_request.refresh_from_db()
        assert self.access_request.is_pending

    def test_first_person_in_a_new_workspace_is_its_owner(self):
        with pytest.raises(MembershipRuleError):
            access.approve_access_request(
                self.access_request, self.reviewer, role="member", new_workspace_name="Acme"
            )
        self.access_request.refresh_from_db()
        assert self.access_request.is_pending

    def test_approve_refuses_an_unknown_role(self):
        existing = baker.make("app.Tenant")
        baker.make("app.Membership", tenant=existing, role="owner")
        with pytest.raises(MembershipRuleError):
            access.approve_access_request(
                self.access_request, self.reviewer, role="god", workspace=existing
            )
        self.access_request.refresh_from_db()
        assert self.access_request.is_pending

    def test_reject_leaves_the_person_out(self):
        with _send_email_patch() as defer, self.captureOnCommitCallbacks(execute=True):
            access.reject_access_request(self.access_request, self.reviewer)

        self.user.refresh_from_db()
        assert not self.user.is_active
        assert self.access_request.status == AccessRequest.Status.REJECTED
        assert not Membership.objects.filter(user=self.user).exists()
        defer.assert_not_called()

    def test_a_reviewed_request_cannot_be_reviewed_again(self):
        with _send_email_patch():
            access.reject_access_request(self.access_request, self.reviewer)

        with pytest.raises(ValueError):
            access.approve_access_request(
                self.access_request, self.reviewer, role="member", new_workspace_name="Acme"
            )


@override_settings(SITE_URL="https://gitgrit.example/")
class TestMailer(TestCase):
    def test_renders_subject_and_body(self):
        send_templated(
            "access_requested",
            ["boss@example.com"],
            {
                "email": "new@example.com",
                "answers": {"company": "Acme", "goals": "Enforce CI"},
                "review_path": "/staff/access-requests/",
            },
        )

        [message] = mail.outbox
        assert message.subject == "GitGrit access request from new@example.com"
        assert message.to == ["boss@example.com"]
        assert "Company: Acme" in message.body
        assert "Enforce CI" in message.body
        assert "https://gitgrit.example/staff/access-requests/" in message.body

    def test_no_recipients_sends_nothing(self):
        send_templated("access_approved", [], {"login_path": "/accounts/login/"})
        assert mail.outbox == []
