"""HealthTrend: healthy projects week by week, as each project stood then."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.cockpit import HealthTrend
from app.domain.models import CommitScore, Project


class HealthTrendTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.today = timezone.localdate()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        Project.objects.filter(pk=self.project.pk).update(created_at=timezone.now() - timedelta(weeks=6))

    def _score(self, value, weeks_ago, branch="main"):
        score = baker.make(CommitScore, project=self.project, branch=branch, value=value, failed=False,
                           ordered_at=timezone.now() - timedelta(weeks=weeks_ago))
        CommitScore.objects.filter(pk=score.pk).update(created_at=timezone.now() - timedelta(weeks=weeks_ago))

    def test_a_project_turns_healthy_the_week_its_score_does(self):
        self._score(40, weeks_ago=3)
        self._score(95, weeks_ago=1)

        points = HealthTrend.weekly(self.tenant, today=self.today)

        self.assertEqual([p.healthy for p in points], [0, 0, 0, 1, 1])
        self.assertEqual({p.total for p in points}, {1})

    def test_other_branches_do_not_count(self):
        self._score(95, weeks_ago=2, branch="feature/x")

        self.assertEqual([p.healthy for p in HealthTrend.weekly(self.tenant, today=self.today)], [0] * 5)

    def test_a_project_counts_from_the_day_it_was_added(self):
        new = baker.make("app.Project", tenant=self.tenant)

        points = HealthTrend.weekly(self.tenant, today=self.today)

        self.assertEqual([p.total for p in points], [1, 1, 1, 1, 2])
