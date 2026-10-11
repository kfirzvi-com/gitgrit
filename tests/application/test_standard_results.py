"""attention_items(): the one "Needs attention" read behind the dashboard card
and the notifications pane."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.standard_results import AttentionItem, attention_items
from app.domain.health import CRITICAL, WARNING
from app.domain.models import StandardExecution

Status = StandardExecution.Status


class AttentionItemsTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _standard(self, name, attach=True, project=None):
        project = project or self.project
        standard = baker.make("app.Standard", tenant=project.tenant, name=name)
        if attach:
            project.standards.add(standard)
        return standard

    def _result(self, standard, score, status=Status.FAILED, project=None, ago=None):
        execution = baker.make(
            "app.StandardExecution", project=project or self.project, standard=standard,
            standard_name=standard.name, score=score, status=status,
        )
        if ago is not None:
            StandardExecution.objects.filter(pk=execution.pk).update(
                created_at=timezone.now() - ago
            )
        return execution

    def test_returns_typed_items_with_ids_not_urls(self):
        standard = self._standard("README present")
        execution = self._result(standard, 20)

        [item] = attention_items(self.tenant)

        self.assertIsInstance(item, AttentionItem)
        self.assertEqual(item.level, CRITICAL)
        self.assertEqual(item.project_id, self.project.pk)
        self.assertEqual(item.project_name, "Acme")
        self.assertEqual(item.standard_id, standard.pk)
        self.assertEqual(item.standard_name, "README present")
        self.assertEqual(item.execution_id, execution.pk)
        self.assertEqual(item.score, 20)
        self.assertEqual(item.status, "Failed")

    def test_levels_follow_the_score_thresholds(self):
        self._result(self._standard("Critical"), 49)
        self._result(self._standard("Warning"), 50)
        self._result(self._standard("Healthy"), 80, status=Status.PASSED)

        levels = {i.standard_name: i.level for i in attention_items(self.tenant)}

        self.assertEqual(levels, {"Critical": CRITICAL, "Warning": WARNING})

    def test_a_failed_run_that_scored_well_is_a_warning(self):
        self._result(self._standard("Flaky"), 90, status=Status.ERROR)

        [item] = attention_items(self.tenant)

        self.assertEqual(item.level, WARNING)

    def test_only_the_latest_result_per_standard_counts(self):
        standard = self._standard("Pinned CI")
        self._result(standard, 10, ago=timedelta(hours=1))
        self._result(standard, 100, status=Status.PASSED)

        self.assertEqual(attention_items(self.tenant), [])

    def test_in_flight_runs_do_not_hide_the_latest_finished_result(self):
        standard = self._standard("Pinned CI")
        self._result(standard, 10, ago=timedelta(hours=1))
        self._result(standard, 0, status=Status.RUNNING)

        [item] = attention_items(self.tenant)

        self.assertEqual(item.score, 10)

    def test_detached_standards_are_ignored(self):
        self._result(self._standard("Attached"), 20)
        self._result(self._standard("Detached", attach=False), 5)

        names = [i.standard_name for i in attention_items(self.tenant)]

        self.assertEqual(names, ["Attached"])

    def test_critical_first_then_newest(self):
        self._result(self._standard("Old critical"), 10, ago=timedelta(days=2))
        self._result(self._standard("New warning"), 60)
        self._result(self._standard("New critical"), 10, ago=timedelta(hours=1))

        names = [i.standard_name for i in attention_items(self.tenant)]

        self.assertEqual(names, ["New critical", "Old critical", "New warning"])

    def test_other_workspaces_are_not_included(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        self._result(self._standard("Elsewhere", project=other), 10, project=other)

        self.assertEqual(attention_items(self.tenant), [])
