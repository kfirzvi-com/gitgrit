"""Confirming an email address and resetting a password, end to end, with
every email going through the outbox onto the branded layout."""
import json
import re
from unittest import mock

import pytest
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AccessRequest, User

HTMX = {"HTTP_HX_REQUEST": "true"}


class _Outbox:
    """Catch what the outbox queues: (template, to, context) per email."""

    def __init__(self, test):
        self.test = test
        self.sent = []

    def __enter__(self):
        self._patch = mock.patch("app.tasks.send_email.defer", side_effect=self._defer)
        self._patch.start()
        self._callbacks = self.test.captureOnCommitCallbacks(execute=True)
        self._callbacks.__enter__()
        return self

    def __exit__(self, *exc):
        self._callbacks.__exit__(*exc)
        self._patch.stop()

    def _defer(self, *, template, to, context):
        self.sent.append((template, to, context))

    def only(self, template):
        [(t, to, context)] = [s for s in self.sent if s[0] == template]
        return to, context


@pytest.mark.django_db
@override_settings(SIGNUP_MODE="approval")
class TestConfirmEmail(TestCase):
    def setUp(self):
        cache.clear()  # allauth's rate limits live there
        baker.make("app.User", is_superuser=True, email="boss@example.com")

    def _sign_up(self):
        with _Outbox(self) as outbox:
            self.client.post(
                reverse("account_login"),
                {"login": "new@example.com", "password": "a-long-passphrase"},
            )
        return outbox

    def test_sign_up_sends_the_confirmation_link_only(self):
        outbox = self._sign_up()

        to, context = outbox.only("email_confirmation_signup")
        assert to == ["new@example.com"]
        assert context["activate_url"].startswith("http://testserver/accounts/confirm-email/")
        assert "access_requested" not in [t for t, _, _ in outbox.sent]

    def test_unconfirmed_requests_dont_reach_superusers(self):
        self._sign_up()
        request = AccessRequest.objects.get(user__email="new@example.com")
        self.client.force_login(User.objects.get(email="boss@example.com"))

        html = self.client.get(reverse("admin_dashboard") + "?status=all").content.decode()
        assert "new@example.com" not in html
        approve = reverse("approve_access_request", args=[request.pk])
        assert self.client.post(approve, {"workspace_name": "Acme", "role": "owner"}).status_code == 404

    def test_following_the_link_confirms_and_tells_superusers(self):
        _, context = self._sign_up().only("email_confirmation_signup")
        confirm_url = context["activate_url"].replace("http://testserver", "")
        self.client.cookies.clear()  # e.g. opened on their phone

        page = self.client.get(confirm_url)
        assert b"Confirm new@example.com" in page.content
        with _Outbox(self) as outbox:
            response = self.client.post(confirm_url)

        assert response.headers["Location"] == reverse("access_request_status")
        assert AccessRequest.objects.get(user__email="new@example.com").is_email_confirmed
        assert outbox.only("access_requested")[0] == ["boss@example.com"]
        assert b"on the list" in self.client.get(reverse("access_request_status")).content

    def test_status_page_waits_for_the_link_and_resends_it(self):
        self._sign_up()
        assert b"Check your inbox" in self.client.get(reverse("access_request_status")).content

        with _Outbox(self) as outbox:
            first = self.client.post(reverse("resend_confirmation"), **HTMX)
        assert outbox.only("email_confirmation")[0] == ["new@example.com"]
        assert json.loads(first["HX-Trigger"])["toast"]["level"] == "success"

        with _Outbox(self) as outbox:
            second = self.client.post(reverse("resend_confirmation"), **HTMX)
        assert outbox.sent == []
        assert json.loads(second["HX-Trigger"])["toast"]["level"] == "warning"

    def test_signing_in_again_before_confirming_lands_on_the_same_page(self):
        self._sign_up()
        self.client.cookies.clear()

        response = self.client.post(
            reverse("account_login"),
            {"login": "new@example.com", "password": "a-long-passphrase"},
        )

        assert response.headers["Location"] == reverse("access_request_status")
        assert b"Check your inbox" in self.client.get(response.headers["Location"]).content


@pytest.mark.django_db
class TestPasswordReset(TestCase):
    def setUp(self):
        cache.clear()

    def test_the_sign_in_box_links_to_it(self):
        html = self.client.get(reverse("account_login")).content.decode()
        assert f'href="{reverse("account_reset_password")}"' in html
        assert "Forgot password?" in html

    def test_reset_link_for_an_account(self):
        user = baker.make("app.User", email="ada@example.com", first_name="Ada")
        user.set_password("old-passphrase-1")
        user.save()
        baker.make("account.EmailAddress", user=user, email="ada@example.com", verified=True, primary=True)

        with _Outbox(self) as outbox:
            response = self.client.post(reverse("account_reset_password"), {"email": "ada@example.com"})

        assert response.headers["Location"] == reverse("account_reset_password_done")
        to, context = outbox.only("password_reset_key")
        assert to == ["ada@example.com"]
        assert context["name"] == "Ada"
        reset_url = context["password_reset_url"]
        assert re.match(r"http://testserver/accounts/password/reset/key/.+/", reset_url)

        # The link leads to a page to choose the new password, which works.
        page = self.client.get(reset_url.replace("http://testserver", ""), follow=True)
        assert b"Choose a new password" in page.content
        done = self.client.post(
            page.redirect_chain[-1][0],
            {"password1": "new-passphrase-2", "password2": "new-passphrase-2"},
        )
        assert done.headers["Location"] == reverse("account_reset_password_from_key_done")
        user.refresh_from_db()
        assert user.check_password("new-passphrase-2")

    def test_no_account_says_so_to_the_address_only(self):
        with _Outbox(self) as outbox:
            response = self.client.post(reverse("account_reset_password"), {"email": "ghost@example.com"})

        # Same page either way, so the form doesn't reveal who has an account.
        assert response.headers["Location"] == reverse("account_reset_password_done")
        assert outbox.only("unknown_account")[0] == ["ghost@example.com"]

    def test_pages_are_on_the_gitgrit_layout(self):
        for name in ("account_reset_password", "account_reset_password_done"):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                assert "— GitGrit</title>" in html


class TestUnknownAllauthEmail(TestCase):
    def test_an_email_we_have_no_template_for_still_goes_out(self):
        from django.core import mail

        from app.presentation.auth_adapters import AccountAdapter

        with mock.patch(
            "allauth.account.adapter.DefaultAccountAdapter.send_mail"
        ) as stock, self.assertLogs("app.access", "WARNING"):
            AccountAdapter().send_mail("account/email/login_code", "ada@example.com", {})
        stock.assert_called_once()
        assert mail.outbox == []
