"""The Critical mark on the project's standards table.

The picker shows the mark per row, the two forms (attach modal, add-project)
post ``critical`` beside ``standards`` and the views write it on the surviving
attachments, the project page shows the F a failing critical standard earns,
names the branch a critical attachment that never ran on is waiting for, and
the Results tab chips the rows that ran under the mark. One test per rule;
the name says which.

Check-all / uncheck-all critical and the critical filter are browser-side
(``standard_picker.html`` JS); the repo has no JS test runner, so these tests
prove the controls are rendered and leave the behaviour to a manual check.
"""
import re
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.application import commit_checks
from app.domain.models import Project, ProjectStandard, StandardExecution
from tests.presentation.test_project_standard_views import (
    NON_MANIFEST_STORAGES,
    _login_member,
    _project,
    _standard,
)
from tests.support import defer_patch


def _critical_box_is_checked(body, standard_pk):
    return re.search(
        rf'<input[^>]*name="critical"[^>]*value="{standard_pk}"[^>]*checked', body
    ) is not None


def _marks(project):
    return {
        row.standard_id: row.critical
        for row in ProjectStandard.objects.filter(project=project)
    }


@pytest.mark.django_db
class TestPickerShowsTheMark(TestCase):
    def test_the_table_shows_the_mark_per_row(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        gate = _standard(tenant, name="Gate")
        plain = _standard(tenant, name="Plain")
        project.standards.add(gate, plain)
        ProjectStandard.objects.filter(project=project, standard=gate).update(critical=True)

        resp = self.client.get(
            reverse("project_standards", args=[project.pk]),
            headers={"HX-Request": "true"},
        )

        body = resp.content.decode()
        assert _critical_box_is_checked(body, gate.pk)
        assert not _critical_box_is_checked(body, plain.pk)

    def test_bulk_critical_buttons_and_filter_are_rendered(self):
        """The JS behind them (only visible rows change; the filter shows
        only marked rows and composes with the search) is checked by hand."""
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        _standard(tenant)

        resp = self.client.get(
            reverse("project_standards", args=[project.pk]),
            headers={"HX-Request": "true"},
        )

        body = resp.content.decode()
        assert "checkAllCriticalStandardPicker(this)" in body
        assert "uncheckAllCriticalStandardPicker(this)" in body
        assert 'class="select select-bordered standard-picker-critical-filter"' in body
        assert '<option value="critical">' in body
        assert '<option value="not-critical">' in body


@pytest.mark.django_db
class TestAttachFormWritesTheMark(TestCase):
    def _post(self, project, standards, critical):
        with defer_patch():
            resp = self.client.post(
                reverse("project_standards", args=[project.pk]),
                data={
                    "standards": [str(s.pk) for s in standards],
                    "critical": [getattr(s, "pk", s) for s in critical],
                },
            )
        assert resp.status_code == 302
        return resp

    def test_resaving_the_table_keeps_marks(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        gate, plain = _standard(tenant), _standard(tenant)

        self._post(project, [gate, plain], critical=[gate])
        assert _marks(project) == {gate.pk: True, plain.pk: False}

        self._post(project, [gate, plain], critical=[gate])
        assert _marks(project) == {gate.pk: True, plain.pk: False}

    def test_unmarking_a_row_clears_it(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        gate = _standard(tenant)
        self._post(project, [gate], critical=[gate])

        self._post(project, [gate], critical=[])

        assert _marks(project) == {gate.pk: False}

    def test_a_mark_on_an_unattached_row_is_ignored(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        attached, loose = _standard(tenant), _standard(tenant)

        self._post(project, [attached], critical=[loose])

        assert _marks(project) == {attached.pk: False}
        assert set(project.standards.all()) == {attached}

    def test_a_posted_id_that_is_not_a_uuid_is_ignored(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        gate = _standard(tenant)

        self._post(project, [gate], critical=["not-an-id", gate])

        assert _marks(project) == {gate.pk: True}

    def test_detach_then_reattach_resets_to_not_critical(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        gate = _standard(tenant)
        self._post(project, [gate], critical=[gate])

        self._post(project, [], critical=[])
        assert _marks(project) == {}

        self._post(project, [gate], critical=[])
        assert _marks(project) == {gate.pk: False}


@pytest.mark.django_db
class TestAddProjectWritesTheMark(TestCase):
    def test_add_project_sets_marks(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github", access_token="ghp_x"
        )
        gate, plain, loose = _standard(tenant), _standard(tenant), _standard(tenant)

        client = mock.Mock()
        client.get_languages.return_value = []
        client.get_topics.return_value = []
        client.create_webhook.return_value = "hook-1"
        with mock.patch(
            "app.presentation.views.project_views.get_platform_client",
            return_value=client,
        ), defer_patch():
            resp = self.client.post(
                reverse("add_project_search", args=[connection.id]),
                data={
                    "external_id": "42",
                    "name": "app",
                    "full_path": "acme/app",
                    "web_url": "https://github.com/acme/app",
                    "default_branch": "main",
                    "lifecycle": "development",
                    "standards": [str(gate.pk), str(plain.pk)],
                    # A mark on an unattached row is ignored here too.
                    "critical": [str(gate.pk), str(loose.pk)],
                },
            )

        assert resp.status_code == 302
        project = Project.objects.get(tenant=tenant, external_id="42")
        assert _marks(project) == {gate.pk: True, plain.pk: False}

    def test_add_project_picker_renders_with_no_marks(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github", access_token="ghp_x"
        )
        s = _standard(tenant)

        with override_settings(STORAGES=NON_MANIFEST_STORAGES):
            resp = self.client.get(reverse("add_project_search", args=[connection.id]))

        assert resp.status_code == 200
        body = resp.content.decode()
        assert f'name="critical" value="{s.pk}"' in body
        assert not _critical_box_is_checked(body, s.pk)


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectPageShowsTheGate(TestCase):
    def _mark(self, project, standard):
        ProjectStandard.objects.filter(project=project, standard=standard).update(critical=True)

    def _run(self, project, standard, status, ref="", **kwargs):
        return baker.make(
            "app.StandardExecution",
            project=project,
            standard=standard,
            standard_name=standard.name,
            event_type="manual",
            ref=ref,
            status=status,
            **kwargs,
        )

    def test_a_failing_critical_shows_f_with_its_name(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant, default_branch="main")
        gate = _standard(tenant, name="No secrets")
        plain = _standard(tenant, name="Readme")
        project.standards.add(gate, plain)
        self._mark(project, gate)
        self._run(project, gate, "failed")
        self._run(project, plain, "passed")

        resp = self.client.get(reverse("project_detail", args=[project.pk]))

        assert resp.status_code == 200
        assert resp.context["grade"].letter == "F"
        assert resp.context["grade"].reason == "No secrets failing"
        assert resp.context["grade_tone"] == "failing"
        assert resp.context["critical_standard_ids"] == {gate.pk}
        body = resp.content.decode()
        assert 'data-grade="F"' in body
        assert "No secrets failing" in body

    def test_a_critical_attachment_with_no_run_on_its_branch_does_not_gate_yet(self):
        """A standard scoped to ``develop`` is graded on develop; until it
        runs there, the page lists it as not evaluated on develop and the
        failing run it has on main changes nothing."""
        _, tenant = _login_member(self.client)
        project = _project(tenant, default_branch="main")
        gate = _standard(
            tenant, name="Develop only", criteria={"events": ["push"], "ref": "develop"}
        )
        project.standards.add(gate)
        self._mark(project, gate)
        self._run(project, gate, StandardExecution.Status.FAILED, ref="")

        resp = self.client.get(reverse("project_detail", args=[project.pk]))

        assert resp.status_code == 200
        assert resp.context["grade"].graded is False
        assert resp.context["not_evaluated_standards"] == [gate]
        body = resp.content.decode()
        assert f'data-not-evaluated-standard="{gate.pk}"' in body
        assert "not evaluated on develop, so it does not gate yet" in body
        assert body.count("data-critical-chip") == 1

    def test_a_branch_scoped_critical_gates_on_its_own_branch(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant, default_branch="main")
        gate = _standard(
            tenant, name="Develop only", criteria={"events": ["push"], "ref": "develop"}
        )
        project.standards.add(gate)
        self._mark(project, gate)
        self._run(project, gate, StandardExecution.Status.FAILED, ref="refs/heads/develop")

        resp = self.client.get(reverse("project_detail", args=[project.pk]))

        assert resp.context["grade"].letter == "F"
        assert resp.context["grade"].reason == "Develop only failing"
        assert resp.context["not_evaluated_standards"] == []

    def test_results_rows_wear_the_chip_the_run_was_graded_under(self):
        """The Results tab reads each row's own snapshot, so a run made
        under the mark keeps its chip after the mark is lifted, and a run
        made before the mark has none."""
        _, tenant = _login_member(self.client)
        project = _project(tenant, default_branch="main")
        gate = _standard(tenant, name="No secrets")
        plain = _standard(tenant, name="Readme")
        project.standards.add(gate, plain)
        check = baker.make("app.CommitCheck", project=project, branch="main", commit_sha="a" * 40)
        marked = self._run(project, gate, "failed", commit_check=check, critical=True)
        unmarked = self._run(project, plain, "passed", commit_check=check, critical=False)
        platform = mock.Mock()
        platform.list_branches.return_value = ["main"]
        platform.list_commits.return_value = [
            {"sha": "a" * 40, "message": "Checked", "author": "Dana", "date": "2026-10-01T10:00:00Z", "url": ""},
        ]

        with mock.patch.object(commit_checks, "_client", return_value=platform):
            resp = self.client.get(reverse("project_history", args=[project.pk]))

        assert resp.status_code == 200
        body = resp.content.decode()
        assert body.count("data-critical-chip") == 1

        def row(execution):
            href = f'href="{reverse("standard_execution_detail", args=[execution.id])}"'
            return body.split(href, 1)[1].split("</a>", 1)[0]

        assert "data-critical-chip" in row(marked)
        assert "data-critical-chip" not in row(unmarked)
