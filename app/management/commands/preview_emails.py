"""Send every GitGrit email, filled with sample data, through the configured
mail backend: with Mailpit running locally (docker compose up -d), they all
land in http://localhost:8025 to look at."""
from django.core.management.base import BaseCommand
from django.urls import reverse

from app.infrastructure.mailer import send_templated


def samples():
    """One sample context per email. Add yours when you add an email."""
    return {
        "access_requested": {
            "email": "margaret@example.test",
            "answers": {
                "name": "Margaret Hamilton",
                "company": "Apollo Systems",
                "role": "Platform lead",
                "goals": "Enforce branch protection and CI checks across our 40 repositories.",
            },
            "review_path": reverse("admin_dashboard") + "#section-access-requests",
        },
        "access_approved": {
            "name": "Margaret Hamilton",
            "workspace": "Apollo Systems",
            "login_path": reverse("account_login"),
        },
    }


class Command(BaseCommand):
    help = "Send a sample of every email to --to (default preview@example.test)."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="preview@example.test")

    def handle(self, *args, to, **options):
        for template, context in samples().items():
            send_templated(template, [to], context)
            self.stdout.write(f"sent {template}")
