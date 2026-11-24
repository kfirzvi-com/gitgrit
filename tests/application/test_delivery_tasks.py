"""The delivery jobs: syncing one project runs on demand, a scheduler asks
for due syncs every minute, and adding them left the other schedules as they
were."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker
from procrastinate.contrib.django import app

from app.models import Platform
from app.tasks import sync_due_deliveries


def schedules() -> dict[str, str]:
    return {periodic.task.name: periodic.cron for periodic in app.periodic_registry.periodic_tasks.values()}


class DeliveryTaskScheduleTests(TestCase):
    def test_syncing_one_project_runs_only_on_demand(self):
        self.assertNotIn("sync_delivery", schedules())

    def test_due_syncs_are_looked_for_every_minute(self):
        self.assertEqual(schedules()["sync_due_deliveries"], "* * * * *")

    def test_stalled_jobs_are_still_recovered_every_two_minutes(self):
        self.assertEqual(schedules()["recover_stalled_jobs"], "*/2 * * * *")

    def test_the_scheduler_asks_for_every_due_git_project_but_not_uploads(self):
        git = baker.make("app.Project", platform=Platform.GITHUB)
        baker.make("app.Project", platform=Platform.ARTIFACT)

        with mock.patch("app.application.delivery.DeliverySyncRequest.send") as send:
            count = sync_due_deliveries(timestamp=0)

        self.assertEqual(count, 1)
        send.assert_called_once_with(git)
