"""Outgoing email: render a template set and hand it to Django's mail backend.

Each email lives under ``app/templates/email/`` as:

- ``<name>_subject.txt`` — one line;
- ``<name>.html`` — the branded version. It extends ``email/base.html``, the
  shared layout, and builds its body from the ``email/_*.html`` components,
  so every email looks the same;
- ``<name>.txt`` — the plain-text version, for clients that don't show HTML
  and for spam filters that like to see one.

The HTML's stylesheet is inlined into each element here (css-inline) and the
``<style>`` block dropped, since many mail clients ignore it.

Which backend sends it is settings' business: SMTP when ``EMAIL_HOST`` is set
(Mailpit locally), the console (the log) otherwise.
"""
import css_inline
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

_inliner = css_inline.CSSInliner(keep_style_tags=False, load_remote_stylesheets=False)


def render(template: str, context: dict) -> tuple[str, str, str]:
    """``(subject, text, html)`` for ``template`` — also used to preview."""
    context = {"site_url": settings.SITE_URL.rstrip("/"), **context}
    subject = " ".join(
        render_to_string(f"email/{template}_subject.txt", context).split()
    )
    context["subject"] = subject
    text = render_to_string(f"email/{template}.txt", context)
    html = _inliner.inline(render_to_string(f"email/{template}.html", context))
    return subject, text, html


def send_templated(template: str, to: list[str], context: dict) -> None:
    if not to:
        return
    subject, text, html = render(template, context)
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, to)
    message.attach_alternative(html, "text/html")
    message.send()
