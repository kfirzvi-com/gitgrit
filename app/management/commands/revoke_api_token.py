"""Revoke (delete) APITokens matching a given prefix.

Scenario harness uses this to simulate mid-session token rotation: mint a
token, start a Claude session, revoke the token, then expect subsequent MCP
calls to fail with 401.
"""
from django.core.management.base import BaseCommand

from app.domain.models import APIToken


class Command(BaseCommand):
    help = "Delete APITokens whose prefix matches --prefix exactly."

    def add_arguments(self, parser):
        parser.add_argument("--prefix", required=True)

    def handle(self, *args, **opts):
        deleted, _ = APIToken.objects.filter(prefix=opts["prefix"]).delete()
        self.stdout.write(f"revoked {deleted}")
