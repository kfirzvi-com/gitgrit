"""The project page's Results tab: branch picker, the branch's score and
results, and its commits with the standards run on each."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import commit_checks
from app.domain.models import StandardExecution

Status = StandardExecution.Status


class ProjectHistoryViewTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Pinned CI")
        self.project.standards.add(self.standard)
        self.platform = mock.Mock()
        self.platform.list_branches.return_value = ["feature/x", "main"]
        self.platform.list_commits.return_value = [
            {"sha": "a" * 40, "message": "Checked commit", "author": "Dana", "date": "2026-10-01T10:00:00Z", "url": ""},
            {"sha": "b" * 40, "message": "Unchecked commit", "author": "Dana", "date": "2026-09-30T10:00:00Z", "url": ""},
        ]
        patch = mock.patch.object(commit_checks, "_client", return_value=self.platform)
        patch.start()
        self.addCleanup(patch.stop)

    def _check(self, sha, branch="main", status=Status.FAILED, score=0, ref=""):
        check = baker.make("app.CommitCheck", project=self.project, branch=branch, commit_sha=sha)
        return baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=status, score=score, commit_check=check, ref=ref,
        )

    def _get(self, **params):
        return self.client.get(reverse("project_history", args=[self.project.pk]), params)

    def test_the_default_branch_is_shown_first_and_selected(self):
        self._check("a" * 40)

        response = self._get()

        self.assertEqual(response.context["branches"], ["main", "feature/x"])
        self.assertEqual(response.context["branch"], "main")
        content = response.content.decode()
        self.assertIn('<option value="main" selected>main (default)</option>', content)
        self.assertIn("Results", content)
        self.assertNotIn("%</span>", content)
        self.assertIn("The project's score", content)

    def test_commits_group_their_results_and_the_rest_say_not_checked(self):
        self._check("a" * 40)

        content = self._get().content.decode()

        self.assertIn(f'data-commit="{"a" * 40}"', content)
        self.assertIn("1 failed", content)
        self.assertIn("Not checked", content)

    def test_another_branch_shows_its_own_results_and_does_not_count(self):
        self._check("c" * 40, branch="feature/x", status=Status.PASSED, score=100, ref="refs/heads/feature/x")

        response = self._get(branch="feature/x")

        self.assertEqual(response.context["status_score"], 100)
        self.assertFalse(response.context["is_default"])
        self.assertIn("Only the default branch counts", response.content.decode())
        self.platform.list_commits.assert_called_with(
            self.project.external_id, self.project.full_path, "feature/x", page=1,
            per_page=commit_checks.COMMITS_PER_PAGE,
        )

    def test_it_polls_while_a_run_is_in_flight(self):
        self._check("a" * 40, status=Status.RUNNING)

        content = self._get().content.decode()

        self.assertIn('hx-trigger="every 5s"', content)
        self.assertIn("1 running", content)

    def test_a_bad_page_number_reads_as_the_first_page(self):
        self.assertEqual(self._get(page="nope").context["page"], 1)

    def test_another_workspaces_project_is_not_found(self):
        other = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        response = self.client.get(reverse("project_history", args=[other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_the_project_page_loads_the_tab_when_first_opened(self):
        content = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()
        self.assertIn(f'hx-get="{reverse("project_history", args=[self.project.pk])}"', content)
        self.assertIn('hx-trigger="intersect once"', content)
        self.platform.list_commits.assert_not_called()


class RunOnBranchViewTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main", languages=[])
        self.standard = baker.make(
            "app.Standard", tenant=self.tenant, name="Pinned CI", enabled=True, draft=False,
            criteria={"events": ["push"], "languages": []},
        )
        self.project.standards.add(self.standard)
        platform = mock.Mock()
        platform.list_branches.return_value = ["main"]
        platform.list_commits.return_value = []
        for patch in (
            mock.patch.object(commit_checks, "_client", return_value=platform),
            mock.patch("app.application.standard_runs.run_standards.configure"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _post(self, **data):
        return self.client.post(reverse("run_on_branch", args=[self.project.pk]), data)

    def test_running_a_commit_pins_the_check_to_it(self):
        response = self._post(branch="main", sha="a" * 40, committed_at="2026-10-01T10:00:00Z")

        from app.domain.models import CommitCheck
        check = CommitCheck.objects.get()
        self.assertEqual((check.branch, check.commit_sha), ("main", "a" * 40))
        self.assertEqual(check.committed_at.isoformat(), "2026-10-01T10:00:00+00:00")
        self.assertEqual(check.executions.get().standard_name, "Pinned CI")
        self.assertIn("Running 1 standard on aaaaaaa.", response.content.decode())

    def test_running_a_branch_waits_for_the_job_to_pin_its_head(self):
        response = self._post(branch="main")

        from app.domain.models import CommitCheck
        self.assertEqual(CommitCheck.objects.get().commit_sha, "")
        self.assertIn("the latest commit on main", response.content.decode())

    def test_a_branch_no_standard_applies_to_runs_nothing(self):
        self.standard.criteria = {"events": ["push"], "languages": [], "ref": "^develop$"}
        self.standard.save()

        response = self._post(branch="main")

        self.assertIn("No standards apply to main.", response.content.decode())

    def test_running_requires_post(self):
        self.assertEqual(self.client.get(reverse("run_on_branch", args=[self.project.pk])).status_code, 405)
