"""Queue an email for the worker (``send_email`` on the notifications queue).

Every email GitGrit sends goes through here, ours and allauth's alike, so
they all render on the shared branded layout (app.infrastructure.mailer) and
none is sent from inside a web request. The context must be JSON: it is
stored with the job.
"""
from django.db import transaction


def send_later(template: str, to: list[str], context: dict) -> None:
    """Queue the email once the surrounding transaction commits, so a rolled
    back change never tells anyone about it."""
    if not to:
        return
    from app.tasks import send_email

    transaction.on_commit(
        lambda: send_email.defer(template=template, to=list(to), context=context)
    )
