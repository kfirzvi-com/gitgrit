"""The Overview tab's summary card: the grade circle, the critical-failures
line, the pass / fail / could-not-run row and the last-run line. Display only;
the grade itself is covered by the grading tests."""
import re

import pytest
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import ProjectStandard, StandardExecution
from app.templatetags.project_tags import trigger_label
from tests.presentation.test_project_standard_views import (
    NON_MANIFEST_STORAGES,
    _login_member,
    _project,
    _standard,
)


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestOverviewCard(TestCase):
    def setUp(self):
        _, self.tenant = _login_member(self.client)
        self.project = _project(self.tenant, default_branch="main")

    def _run(self, status, critical=False, **kwargs):
        standard = _standard(self.tenant)
        self.project.standards.add(standard)
        if critical:
            ProjectStandard.objects.filter(project=self.project, standard=standard).update(level="critical")
        kwargs.setdefault("event_type", "manual")
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, status=status, **kwargs,
        )

    def _page(self):
        return self.client.get(reverse("project_detail", args=[self.project.pk]))

    def test_a_failing_critical_counts_and_reads_in_red_with_an_f(self):
        self._run("failed", critical=True)
        self._run("error", critical=True)
        self._run("passed")

        response = self._page()

        assert response.context["grade"].letter == "F"
        assert response.context["critical_failed_count"] == 2
        body = response.content.decode()
        assert 'data-critical-failed="2"' in body
        assert "2 critical standards failed" in body
        assert "gg-tone-failing gg-tone-text font-semibold" in body

    def test_one_critical_reads_in_the_singular(self):
        self._run("failed", critical=True)

        assert "1 critical standard failed" in self._page().content.decode()

    def test_the_count_is_zero_exactly_when_the_grade_is_not_f(self):
        self._run("failed")  # not critical: a D or worse, never the gate
        self._run("passed", critical=True)

        response = self._page()

        assert response.context["grade"].letter != "F"
        assert response.context["critical_failed_count"] == 0
        body = response.content.decode()
        assert 'data-critical-failed="0"' in body
        assert "0 critical standards failed" in body
        assert "gg-tone-failing gg-tone-text font-semibold" not in body

    def test_could_not_run_links_to_the_notification_panel_when_above_zero(self):
        self._run("passed")
        self._run("error")

        body = self._page().content.decode()

        assert "data-errors-link" in body
        assert re.search(r"<a [^>]*data-notification-open[^>]*data-errors-link", body)
        assert "could not run" in body

    def test_could_not_run_is_plain_text_at_zero(self):
        self._run("passed")

        body = self._page().content.decode()

        assert "data-errors-link" not in body
        assert "could not run" in body

    def test_the_last_run_line_names_the_newest_run_and_its_trigger(self):
        self._run("passed", event_type="manual")
        newest = self._run("passed", event_type="push", ref="refs/tags/v1")

        body = self._page().content.decode()

        assert "data-last-run" in body
        assert f"{newest.created_at:%-d %b %Y}" in body
        assert "triggered by Tag" in body

    def test_the_summary_card_has_no_grade_explanation_tooltip(self):
        self._run("passed")

        body = self._page().content.decode()

        assert "About this grade" not in body
        assert "any critical standard failing" not in body

    def test_the_about_box_links_the_platform_to_the_repository(self):
        self.project.platform = "github"
        self.project.web_url = "https://github.com/acme/api"
        self.project.save()

        body = self._page().content.decode()

        match = re.search(r"<a [^>]*data-repo-link[^>]*>", body)
        assert match
        tag = match.group(0)
        assert 'href="https://github.com/acme/api"' in tag
        assert 'target="_blank"' in tag
        assert 'rel="noopener noreferrer"' in tag
        assert f'aria-label="Open {self.project.name} on GitHub"' in tag

    def test_the_about_box_shows_plain_text_without_a_repository_url(self):
        self.project.web_url = ""
        self.project.save()

        assert "data-repo-link" not in self._page().content.decode()

    def test_an_empty_project_shows_the_dashed_circle_and_its_message(self):
        self.project.standards.add(_standard(self.tenant))

        body = self._page().content.decode()

        assert "border-dashed" in body
        assert "No results on main yet." in body
        assert "data-grade=" not in body
        assert "data-last-run" not in body


class TestTriggerLabel(SimpleTestCase):
    def _label(self, event_type, ref=""):
        return trigger_label(StandardExecution(event_type=event_type, ref=ref))

    def test_known_events(self):
        assert self._label("manual") == "Manual"
        assert self._label("pull_request", "feature") == "Pull request"
        assert self._label("push", "refs/heads/main") == "Push"
        assert self._label("push", "") == "Push"

    def test_a_tag_ref_reads_tag_for_push_and_create(self):
        assert self._label("push", "refs/tags/v1.0") == "Tag"
        assert self._label("create", "refs/tags/v1.0") == "Tag"

    def test_a_create_without_a_tag_ref_stays_create(self):
        assert self._label("create", "v1.0") == "Create"
        assert self._label("create", "") == "Create"

    def test_anything_else_is_made_readable(self):
        assert self._label("issue_comment") == "Issue comment"
