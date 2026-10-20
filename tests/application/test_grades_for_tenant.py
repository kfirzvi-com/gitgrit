"""``grades_for_tenant``: the workspace-wide read agrees with
``grade_for_project`` and costs a fixed number of queries."""
import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.grading_service import (
    grade_for_project,
    grades_for_tenant,
    letter_for_projects,
)
from app.domain.grading import NO_GRADE
from app.domain.models import StandardExecution

Status = StandardExecution.Status
Origin = StandardExecution.ErrorOrigin


def _run(project, standard, status=Status.PASSED, **kwargs):
    kwargs.setdefault("event_type", "manual")
    kwargs.setdefault("ref", "")
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        status=status,
        **kwargs,
    )


@pytest.mark.django_db
class TestGradesForTenant(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def _project(self, **kwargs):
        return baker.make("app.Project", tenant=self.tenant, **kwargs)

    def _standard(self, project, critical=False, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant, **kwargs)
        project.standards.add(standard)
        if critical:
            project.project_standards.filter(standard=standard).update(level="critical")
        return standard

    def test_agrees_with_grade_for_project(self):
        """Every gathering rule at once: draft/disabled/detached ignored,
        other-branch runs (a pull request, a feature push) ignored, platform
        errors keep the previous result, running rows skipped, critical mark
        read from the link."""
        p1 = self._project(default_branch="main")
        p2 = self._project(default_branch="develop")
        p3 = self._project()  # nothing attached: no grade

        gate = self._standard(p1, critical=True, name="gate")
        ok = self._standard(p1, name="ok")
        draft = self._standard(p1, name="draft", draft=True)
        off = self._standard(p1, name="off", enabled=False)
        detached = baker.make("app.Standard", tenant=self.tenant, name="detached")
        _run(p1, gate, Status.PASSED)
        _run(p1, gate, Status.FAILED, event_type="pull_request", ref="feature")
        _run(p1, gate, Status.ERROR, error_origin=Origin.PLATFORM)
        _run(p1, ok, Status.FAILED, event_type="push", ref="refs/heads/other")
        _run(p1, ok, Status.PASSED, event_type="push", ref="refs/heads/main")
        _run(p1, ok, Status.RUNNING)
        _run(p1, draft, Status.FAILED)
        _run(p1, off, Status.FAILED)
        _run(p1, detached, Status.FAILED)

        a = self._standard(p2, name="a")
        b = self._standard(p2, name="b")
        _run(p2, a, Status.PASSED, event_type="push", ref="refs/heads/develop")
        _run(p2, b, Status.ERROR, error_origin=Origin.STANDARD)
        _run(p2, b, Status.PASSED, event_type="push", ref="refs/heads/main")  # not p2's default

        grades = grades_for_tenant(self.tenant)

        assert set(grades) == {p1.pk, p2.pk, p3.pk}
        for project in (p1, p2, p3):
            single = grade_for_project(project)
            tenant_wide = grades[project.pk]
            assert tenant_wide.grade == single.grade, project
            assert [e.pk for e in tenant_wide.executions] == [e.pk for e in single.executions]
            assert [s.pk for s in tenant_wide.not_evaluated] == [s.pk for s in single.not_evaluated]
            assert tenant_wide.levels == single.levels
        assert grades[p1.pk].grade.letter == "A+"
        assert grades[p2.pk].grade.letter == "D"
        assert grades[p3.pk].grade.letter == NO_GRADE

    def test_other_workspaces_are_not_read(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        standard = baker.make("app.Standard", tenant=other.tenant)
        other.standards.add(standard)
        _run(other, standard)

        assert grades_for_tenant(self.tenant) == {}

    def test_query_count_does_not_grow_with_projects(self):
        for _ in range(3):
            project = self._project()
            _run(project, self._standard(project))

        # Projects, attachments, then current_results (its pairs and rows).
        with self.assertNumQueries(4):
            grades = grades_for_tenant(self.tenant)
        assert len(grades) == 3

    def test_letter_for_projects_is_worst_of_graded(self):
        good = self._project()
        bad = self._project()
        empty = self._project()
        _run(good, self._standard(good))
        _run(bad, self._standard(bad), Status.FAILED)
        grades = grades_for_tenant(self.tenant)

        assert letter_for_projects([good.pk, bad.pk, empty.pk], grades) == "D"
        assert letter_for_projects([good.pk, empty.pk], grades) == "A+"
        assert letter_for_projects([empty.pk], grades) == NO_GRADE
