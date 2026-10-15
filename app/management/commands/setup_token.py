"""Print the first-run setup token.

    python manage.py setup_token

A fresh deployment sends every page to /setup/, which asks for this token
before it creates the first superuser.
"""
from django.core.management.base import BaseCommand

from app.application.access import setup_required, setup_token


class Command(BaseCommand):
    help = "Print the token first-run setup (/setup/) asks for."

    def handle(self, *args, **opts):
        self.stdout.write(setup_token())
        if not setup_required():
            self.stderr.write("Setup is already done: this deployment has users.")
