"""Every GitGrit email shares one branded HTML layout (email/base.html), has
a plain-text twin, and is sent with its styles inlined."""
import re
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from app.infrastructure.mailer import render, send_templated
from app.management.commands.preview_emails import samples

EMAIL_DIR = Path(settings.BASE_DIR) / "app" / "templates" / "email"


def _emails():
    return sorted(p.stem for p in EMAIL_DIR.glob("*.txt") if not p.stem.endswith("_subject"))


@override_settings(SITE_URL="https://gitgrit.example/")
class MailerTests(TestCase):
    def test_sends_text_with_a_branded_html_alternative(self):
        send_templated("access_approved", ["ada@example.com"], samples()["access_approved"])

        [message] = mail.outbox
        assert message.subject == "You're in: your GitGrit access is approved"
        assert "Apollo Systems" in message.body  # the plain-text twin
        [(html, mimetype)] = message.alternatives
        assert mimetype == "text/html"
        assert "You're in" in html
        assert 'href="https://gitgrit.example/accounts/login/"' in html
        assert "https://gitgrit.example/static/app/images/email-logo" in html

    def test_styles_are_inlined_for_mail_clients(self):
        _, _, html = render("access_requested", samples()["access_requested"])

        assert '<h1 style="' in html
        [button] = re.findall(r"<a [^>]*button-link[^>]*>", html)
        assert "display: inline-block" in button and "background" not in button
        # Inlined, not shipped: many clients drop <style> (Mailpit's HTML check).
        assert "<style" not in html

    def test_every_email_uses_the_shared_layout_and_has_all_its_parts(self):
        for name in _emails():
            with self.subTest(email=name):
                assert (EMAIL_DIR / f"{name}_subject.txt").exists()
                html_template = (EMAIL_DIR / f"{name}.html").read_text()
                assert '{% extends "email/base.html" %}' in html_template
                subject, text, html = render(name, samples()[name])
                assert subject and text.strip()
                assert "You received this because" in html

    def test_preview_sends_one_of_each(self):
        call_command("preview_emails", "--to", "me@example.com", stdout=open("/dev/null", "w"))

        assert sorted(m.subject for m in mail.outbox) == sorted(
            render(name, samples()[name])[0] for name in _emails()
        )
        assert all(m.to == ["me@example.com"] for m in mail.outbox)


@override_settings(
    EMAIL_BACKEND="django_ses.SESBackend",
    AWS_SES_REGION_NAME="eu-north-1",
    AWS_SES_REGION_ENDPOINT="email.eu-north-1.amazonaws.com",
    USE_SES_V2=True,
    SITE_URL="https://gitgrit.example/",
)
class SesBackendTests(TestCase):
    """With GITGRIT_EMAIL_BACKEND=ses, the same email goes out through the SES
    v2 API, credentials from the host's AWS role (none in settings)."""

    def test_sends_the_branded_email_through_sesv2(self):
        from unittest import mock

        with mock.patch("boto3.Session") as session:
            client = session.return_value.client.return_value
            client.send_email.return_value = {
                "MessageId": "m-1", "ResponseMetadata": {"RequestId": "r-1"}
            }
            send_templated("access_approved", ["ada@example.com"], samples()["access_approved"])

        # No keys from settings: boto3 falls back to the instance role.
        session.assert_called_once_with(
            aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None
        )
        assert session.return_value.client.call_args.args == ("sesv2",)
        assert session.return_value.client.call_args.kwargs["region_name"] == "eu-north-1"
        kwargs = client.send_email.call_args.kwargs
        assert kwargs["FromEmailAddress"] == settings.DEFAULT_FROM_EMAIL
        assert kwargs["Destination"]["ToAddresses"] == ["ada@example.com"]
        raw = kwargs["Content"]["Raw"]["Data"].decode()
        assert "multipart/alternative" in raw and "text/html" in raw
