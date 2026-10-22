"""The Results tab's run timeline: an open commit lists every run of the
standards on it, oldest first, the newest selected (the commit reads it);
arrows and nodes load another run's results in place."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from unittest import mock

from app.application import scoring
from app.application.commit_checks import CommitRow, commit_runs
from app.domain.models import StandardExecution

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
Status = StandardExecution.Status
SHA = "a" * 40


class SelectionTests(SimpleTestCase):
    def runs(self, n):
        return [mock.Mock(check=mock.Mock(pk=i)) for i in range(n)]

    def test_the_newest_run_is_selected_by_default(self):
        runs = self.runs(3)
        row = CommitRow(sha=SHA, checks=runs)

        assert (row.selected, row.selected_index, row.previous_check, row.next_check) == (runs[2], 2, runs[1], None)

    def test_a_picked_run_with_its_neighbours(self):
        runs = self.runs(3)
        row = CommitRow(sha=SHA, checks=runs, selected_id=1)

        assert (row.selected, row.previous_check, row.next_check) == (runs[1], runs[0], runs[2])

    def test_the_oldest_has_nothing_before_and_an_unknown_pick_falls_back_to_the_newest(self):
        runs = self.runs(2)
        assert CommitRow(sha=SHA, checks=runs, selected_id=0).previous_check is None
        assert CommitRow(sha=SHA, checks=runs, selected_id="gone").selected is runs[1]

    def test_an_unchecked_commit_has_no_runs(self):
        row = CommitRow(sha=SHA)
        assert (row.selected, row.previous_check, row.next_check) == (None, None, None)


class Fixture(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main", languages=[])
        self.lint = baker.make("app.Standard", tenant=self.tenant, name="Lint", enabled=True, draft=False, criteria={})
        self.docs = baker.make("app.Standard", tenant=self.tenant, name="Docs", enabled=True, draft=False, criteria={})
        self.project.standards.add(self.lint, self.docs)
        now = timezone.now()
        # First run: Docs errored. Second, a day later: both passed.
        self.first = self.checked_at(now - timedelta(days=1), {self.lint: Status.PASSED, self.docs: Status.ERROR})
        self.second = self.checked_at(now, {self.lint: Status.PASSED, self.docs: Status.PASSED})

    def checked_at(self, at, statuses):
        check = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha=SHA, event_type="manual",
            expected_standard_ids=[str(self.lint.pk), str(self.docs.pk)],
        )
        type(check).objects.filter(pk=check.pk).update(created_at=at)
        check.refresh_from_db()
        for standard, status in statuses.items():
            baker.make(
                "app.StandardExecution", project=self.project, standard=standard, standard_name=standard.name,
                commit_check=check, status=status, score=100 if status == Status.PASSED else 0, ref="main",
            )
        scoring.score_check(check)
        return check


class CommitRunsTests(Fixture):
    def test_a_check_s_commit_with_every_run_and_that_one_selected(self):
        row = commit_runs(self.project, self.first.pk)

        assert [r.check for r in row.checks] == [self.first, self.second]
        assert (row.selected.check, row.selected.outcome, row.selected.standing.reason) == (self.first, "no_score", "Docs errored")
        assert row.shown.outcome == "scored"

    def test_another_project_s_check_is_not_found(self):
        assert commit_runs(baker.make("app.Project"), self.first.pk) is None


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TimelineViewTests(Fixture):
    def history(self):
        with mock.patch("app.application.commit_checks._client", side_effect=RuntimeError("down")):
            return self.client.get(reverse("project_history", args=[self.project.pk]), HTTP_HX_REQUEST="true").content.decode()

    def test_an_open_commit_shows_its_runs_oldest_first_the_newest_selected(self):
        body = self.history()

        assert "data-check-timeline" in body
        assert body.index('data-check-node="no_score"') < body.index('data-check-node="scored"')
        assert "Run 2 of 2" in body
        assert "the commit&#x27;s outcome" in body or "the commit's outcome" in body
        assert 'data-check-next' in body and 'disabled' in body[body.index('data-check-next') - 300:body.index('data-check-next')]

    def test_picking_an_earlier_run_shows_its_results_in_place(self):
        url = reverse("project_commit_check", args=[self.project.pk, self.first.pk])

        body = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()

        assert body.lstrip().startswith("<div") and "data-commit-runs" in body
        assert "Run 1 of 2" in body
        assert "an earlier run: the commit reads its newest" in body
        assert "Docs errored" in body
        assert 'data-result-group="errored"' in body
        assert reverse("project_commit_check", args=[self.project.pk, self.second.pk]) in body

    def test_another_workspace_s_check_is_404(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        check = baker.make("app.CommitCheck", project=other, commit_sha=SHA)

        assert self.client.get(reverse("project_commit_check", args=[self.project.pk, check.pk])).status_code == 404
        assert self.client.get(reverse("project_commit_check", args=[other.pk, check.pk])).status_code == 404
