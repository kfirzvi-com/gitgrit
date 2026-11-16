"""The delivery jobs: refreshing one project runs on demand, refreshing all
runs on a schedule, and adding them left the other schedules as they were."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker
from procrastinate.contrib.django import app

from app.models import Platform
from app.tasks import refresh_all_deployments


def schedules() -> dict[str, str]:
    return {periodic.task.name: periodic.cron for periodic in app.periodic_registry.periodic_tasks.values()}


class DeliveryTaskScheduleTests(TestCase):
    def test_refreshing_one_project_runs_only_on_demand(self):
        self.assertNotIn("refresh_deployments", schedules())

    def test_every_project_is_refreshed_four_times_a_day(self):
        self.assertEqual(schedules()["refresh_all_deployments"], "17 */6 * * *")

    def test_stalled_jobs_are_still_recovered_every_two_minutes(self):
        self.assertEqual(schedules()["recover_stalled_jobs"], "*/2 * * * *")

    def test_refreshing_all_asks_for_every_git_project_but_not_uploads(self):
        git = baker.make("app.Project", platform=Platform.GITHUB)
        baker.make("app.Project", platform=Platform.ARTIFACT)

        with mock.patch("app.application.delivery.DeploymentRefreshRequest.send") as send:
            count = refresh_all_deployments(timestamp=0)

        self.assertEqual(count, 1)
        send.assert_called_once_with(git)
