"""``ProjectHealthService.health``: the project summary reads the same rows
as the letter, so counts never disagree with it."""
from datetime import timedelta

import pytest
from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.project_health_service import ProjectHealthService
from app.domain.models import Standard, StandardExecution

Status = StandardExecution.Status
Origin = StandardExecution.ErrorOrigin


@pytest.mark.django_db
class TestProjectHealthCounts(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self._clock = timezone.now() - timedelta(hours=1)

    def _run(self, name, status, *, draft=False, error_origin=Origin.STANDARD, score=100):
        standard = Standard.objects.filter(
            tenant=self.tenant, name=name
        ).first() or baker.make(
            "app.Standard", tenant=self.tenant, name=name, enabled=True, draft=draft
        )
        self.project.standards.add(standard)
        self._clock += timedelta(minutes=1)
        row = baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=name, ref="main", status=status, score=score,
            error_origin=error_origin,
        )
        StandardExecution.objects.filter(pk=row.pk).update(created_at=self._clock)

    def test_counts_and_score_match_the_letters_rows(self):
        self._run("ok", Status.PASSED, score=100)
        self._run("bad", Status.FAILED, score=0)
        # A GitGrit failure keeps the previous result: it must not count.
        self._run("flaky", Status.PASSED, score=100)
        self._run("flaky", Status.ERROR, error_origin=Origin.PLATFORM, score=0)
        # A draft standard never counts.
        self._run("wip", Status.FAILED, draft=True, score=0)

        body = ProjectHealthService().health(self.tenant, str(self.project.id))

        assert (body["passed"], body["failed"], body["errored"]) == (2, 1, 0)
        assert body["grade"] == "C"
        assert body["score"] == 67
        assert {r["standard_name"] for r in body["results"]} == {"ok", "bad", "flaky"}
