"""seed_delivery: synthetic deployments and pull requests for the demo
projects, only in the workspace asked for, and removable without touching
real rows."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.models import Deployment, Project, PullRequest


class SeedDeliveryTests(TestCase):
    def setUp(self):
        self.mine = baker.make(Project, name="gitgrit-demo-orders-service", tenant__name="Mine")
        self.other = baker.make(Project, name="gitgrit-demo-orders-service", tenant__name="Other")
        now = timezone.now()
        self.real = baker.make(PullRequest, project=self.mine, number=1, url="https://example.test/1",
                               created_at=now, updated_at=now)

    def seed(self, *args):
        call_command("seed_delivery", *args, stdout=StringIO())

    def test_seeds_only_the_workspace_asked_for(self):
        self.seed("--workspace", "Mine")

        self.assertTrue(Deployment.objects.filter(project=self.mine).exists())
        self.assertGreater(PullRequest.objects.filter(project=self.mine, state="open").count(), 1)
        self.assertFalse(Deployment.objects.filter(project=self.other).exists())

    def test_clear_removes_seeded_rows_and_keeps_real_ones(self):
        self.seed()

        self.seed("--clear")

        self.assertFalse(Deployment.objects.exists())
        self.assertEqual(list(PullRequest.objects.all()), [self.real])
