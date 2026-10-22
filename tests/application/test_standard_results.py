"""attention_items(): the one "Needs attention" read behind the dashboard card
and the notifications pane."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.standard_results import (
    AttentionItem,
    attention_items,
    current_results,
    project_score,
)
from app.domain.score_representation import ScoreTone
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
        self.assertEqual(item.level, ScoreTone.NEEDS_ATTENTION)
        self.assertEqual(item.project_id, self.project.pk)
        self.assertEqual(item.project_name, "Acme")
        self.assertEqual(item.standard_id, standard.pk)
        self.assertEqual(item.standard_name, "README present")
        self.assertEqual(item.execution_id, execution.pk)
        self.assertEqual(item.score, 20)
        self.assertEqual(item.status, "Failed")

    def test_runs_that_failed_or_could_not_run_need_attention_whatever_their_score(self):
        self._result(self._standard("Failed high"), 95)
        self._result(self._standard("Could not run"), 0, status=Status.ERROR)
        self._result(self._standard("Passed low"), 10, status=Status.PASSED)

        names = {i.standard_name for i in attention_items(self.tenant)}

        self.assertEqual(names, {"Failed high", "Could not run"})

    def test_a_run_that_fails_its_project_is_failed_and_comes_first(self):
        self._result(self._standard("Major"), 10)
        required = self._result(self._standard("Required"), 50, ago=timedelta(days=1))
        StandardExecution.objects.filter(pk=required.pk).update(importance="required")

        items = attention_items(self.tenant)

        self.assertEqual(
            [(i.standard_name, i.level) for i in items],
            [("Required", ScoreTone.FAILED), ("Major", ScoreTone.NEEDS_ATTENTION)],
        )

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

    def test_newest_first_within_a_level(self):
        self._result(self._standard("Old"), 10, ago=timedelta(days=2))
        self._result(self._standard("New"), 60)

        names = [i.standard_name for i in attention_items(self.tenant)]

        self.assertEqual(names, ["New", "Old"])

    def test_other_workspaces_are_not_included(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        self._result(self._standard("Elsewhere", project=other), 10, project=other)

        self.assertEqual(attention_items(self.tenant), [])


class HomeBranchTests(TestCase):
    """Health reads each standard's home branch only: the default branch, or
    the branch its Branch/Tag Filter names literally."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")

    def _standard(self, name="Pinned CI", ref_filter=None):
        criteria = {"ref": ref_filter} if ref_filter is not None else {}
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, criteria=criteria)
        self.project.standards.add(standard)
        return standard

    def _run(self, standard, score, ref="", status=Status.FAILED, ago=None, event_type="push"):
        execution = baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, score=score, status=status, ref=ref,
            event_type=event_type,
        )
        if ago is not None:
            StandardExecution.objects.filter(pk=execution.pk).update(created_at=timezone.now() - ago)
        return execution

    def test_a_failing_feature_branch_does_not_override_a_passing_default_branch(self):
        standard = self._standard()
        self._run(standard, 100, ref="refs/heads/main", status=Status.PASSED, ago=timedelta(hours=1))
        self._run(standard, 0, ref="refs/heads/feature/wip")

        self.assertEqual(attention_items(self.tenant), [])

    def test_a_fix_on_a_feature_branch_does_not_hide_the_default_branch_failure(self):
        standard = self._standard()
        self._run(standard, 10, ref="", ago=timedelta(hours=1))
        self._run(standard, 100, ref="refs/heads/feature/fix", status=Status.PASSED)

        [item] = attention_items(self.tenant)
        self.assertEqual(item.score, 10)

    def test_pull_request_runs_do_not_count(self):
        standard = self._standard()
        self._run(standard, 0, ref="feature/x", event_type="pull_request")

        self.assertEqual(current_results([self.project]), [])

    def test_every_spelling_of_the_default_branch_counts(self):
        for ref in ("", "main", "refs/heads/main"):
            with self.subTest(ref=ref):
                StandardExecution.objects.all().delete()
                standard = self._standard(name=f"S {ref}")
                self._run(standard, 10, ref=ref)
                self.assertEqual(len(current_results([self.project])), 1)

    def test_a_project_with_another_default_branch(self):
        self.project.default_branch = "trunk"
        self.project.save()
        standard = self._standard()
        self._run(standard, 10, ref="refs/heads/main", ago=timedelta(hours=1))
        trunk = self._run(standard, 20, ref="refs/heads/trunk")

        self.assertEqual([r.pk for r in current_results([self.project])], [trunk.pk])

    def test_a_standard_filtered_to_one_branch_counts_on_that_branch(self):
        standard = self._standard(ref_filter="^develop$")
        self._run(standard, 100, ref="", status=Status.PASSED, ago=timedelta(hours=1))
        develop = self._run(standard, 10, ref="refs/heads/develop")

        self.assertEqual([r.pk for r in current_results([self.project])], [develop.pk])

    def test_a_regex_filter_counts_on_the_default_branch(self):
        standard = self._standard(ref_filter="^release/.*")
        default = self._run(standard, 10, ref="", ago=timedelta(hours=1))
        self._run(standard, 100, ref="refs/heads/release/1.0", status=Status.PASSED)

        self.assertEqual([r.pk for r in current_results([self.project])], [default.pk])

    def test_statuses_and_exclusions(self):
        standard = self._standard()
        passed = self._run(standard, 100, status=Status.PASSED, ago=timedelta(hours=2))
        errored = self._run(standard, 0, status=Status.ERROR, ago=timedelta(hours=1))
        newest = self._run(standard, 50)

        self.assertEqual([r.pk for r in current_results([self.project])], [newest.pk])
        self.assertEqual(
            [r.pk for r in current_results([self.project], statuses=(Status.PASSED,))], [passed.pk]
        )
        self.assertEqual(
            [r.pk for r in current_results([self.project], exclude_execution_ids=[newest.pk])],
            [errored.pk],
        )

    def test_project_score_averages_and_handles_nothing(self):
        self.assertIsNone(project_score([]))
        a, b = self._standard("A"), self._standard("B")
        self._run(a, 100, status=Status.PASSED)
        self._run(b, 51)
        self.assertEqual(project_score(current_results([self.project])), 76)
