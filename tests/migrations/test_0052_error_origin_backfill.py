"""Migration 0047 marks the ERROR rows GitGrit itself caused as platform
errors, so past outages do not count against a grade. It matches the three
writers' shapes only: the stale sweep, the job's ``_fail`` and the sandbox
runner. Every other error stays "standard"."""
from importlib import import_module

import pytest
from django.apps import apps
from django.test import TestCase
from model_bakery import baker

from app.application.standard_runs import STALE_MESSAGE
from app.domain.models import StandardExecution

Status = StandardExecution.Status
Origin = StandardExecution.ErrorOrigin


@pytest.mark.django_db
class ErrorOriginBackfillTests(TestCase):
    def setUp(self):
        tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=tenant)
        self.standard = baker.make("app.Standard", tenant=tenant)
        self.migration = import_module("app.migrations.0052_standardexecution_error_origin")

    def _row(self, status=Status.ERROR, message="", details=None):
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            status=status,
            message=message,
            details=details if details is not None else {},
            error_origin=Origin.STANDARD,
        )

    def _origins(self, *rows):
        return [StandardExecution.objects.get(pk=r.pk).error_origin for r in rows]

    def test_gitgrit_caused_errors_become_platform(self):
        stale_text = STALE_MESSAGE.format(minutes=15)
        stale = self._row(message=stale_text, details={"error": stale_text})
        old_stale = self._row(
            message="Run did not finish within 5 minutes. Old wording.",
            details={"error": "Run did not finish within 5 minutes. Old wording."},
        )
        job = self._row(message="connection refused", details={"error": "connection refused"})
        gone = self._row(message="standard no longer exists", details={"error": "standard no longer exists"})
        sandbox = self._row(message="Sandbox error: docker is down", details={"error": True})
        parse = self._row(message="Failed to parse standard output", details={"error": True})

        self.migration.mark_platform_errors(apps, None)

        assert self._origins(stale, old_stale, job, gone, sandbox, parse) == [Origin.PLATFORM] * 6

    def test_everything_else_stays_standard(self):
        raised = self._row(message="Traceback ... ValueError", details={"error": True})
        text_differs = self._row(message="bad config", details={"error": "something else"})
        no_details = self._row(message="boom")
        failed = self._row(status=Status.FAILED, message="Sandbox error: x", details={"error": True})
        passed = self._row(status=Status.PASSED, message="ok")

        self.migration.mark_platform_errors(apps, None)

        assert self._origins(raised, text_differs, no_details, failed, passed) == [Origin.STANDARD] * 5
