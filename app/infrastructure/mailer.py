"""Outgoing email: render a template pair and hand it to Django's mail backend.

Each email is two templates under ``app/templates/email/``:
``<name>_subject.txt`` (one line) and ``<name>.txt`` (the body). Plain text
only, which every client renders and no spam filter frowns at.

Which backend sends it is settings' business: SMTP when ``EMAIL_HOST`` is set,
the console (the log) otherwise.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


def send_templated(template: str, to: list[str], context: dict) -> None:
    if not to:
        return
    context = {"site_url": settings.SITE_URL.rstrip("/"), **context}
    subject = " ".join(
        render_to_string(f"email/{template}_subject.txt", context).split()
    )
    body = render_to_string(f"email/{template}.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to)
