"""Every place a project's score shows says when it is not the latest
commit's: the newest commit has no score (a standard errored or never ran),
so the score shown is an older commit's (or there is none). And "Needs
attention" explains what it lists."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application import scoring
from app.application.project_health_counts import ProjectHealthCounts
from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution
from app.presentation.architecture import stack_graph, workspace_graph
from app.presentation.older_commit_note import OlderCommitNote

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
Status = StandardExecution.Status
OLD, NEW = "1" * 40, "2" * 40


class OlderCommitNoteTests(SimpleTestCase):
    def score(self, sha, reason=""):
        return baker.prepare("app.CommitScore", commit_sha=sha, reason=reason)

    def test_names_the_commit_shown_the_newest_and_why(self):
        assert OlderCommitNote.text(self.score(NEW, "Lint errored"), self.score(OLD)) == (
            "Not the latest commit: showing 1111111. The newest, 2222222, has no score (Lint errored)."
        )

    def test_with_nothing_shown_it_says_there_is_no_score(self):
        assert OlderCommitNote.text(self.score(NEW, "Docs not run")) == (
            "No score: the newest commit, 2222222, has none (Docs not run)."
        )

    def test_a_score_with_no_reason_on_record(self):
        assert "(not every standard has a result)" in OlderCommitNote.text(self.score(NEW), self.score(OLD))


class Fixture(TestCase):
    """A project scored on an older commit whose newest commit has no score
    because a standard errored."""

    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, name="Backend", default_branch="main", languages=[])
        self.lint = self._standard("Lint")
        self.docs = self._standard("Docs")
        now = timezone.now()
        self.verdict = self._commit(OLD, now - timedelta(days=1), Status.PASSED)
        self.newest = self._commit(NEW, now, Status.ERROR)

    def _component(self):
        """The project's own component (every project has one at its root)."""
        component = self.project.components.first() or baker.make(
            "app.Component", tenant=self.tenant, project=self.project, name="api"
        )
        component.name = "api"
        component.save()
        return component

    def _standard(self, name, project=None):
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, enabled=True, draft=False, criteria={})
        (project or self.project).standards.add(standard)
        return standard

    def _commit(self, sha, committed_at, lint_status, project=None, branch="main"):
        project = project or self.project
        standards = list(project.standards.all())
        check = baker.make(
            "app.CommitCheck", project=project, branch=branch, commit_sha=sha, committed_at=committed_at,
            expected_standard_ids=[str(s.pk) for s in standards],
        )
        for s in standards:
            baker.make(
                "app.StandardExecution", project=project, standard=s, standard_name=s.name, commit_check=check,
                status=lint_status if s.name == "Lint" else Status.PASSED, score=100, ref=branch,
            )
        return scoring.score_check(check)


class NewestWithoutScoreTests(Fixture):
    def test_a_project_whose_newest_commit_has_no_score(self):
        assert scoring.newest_without_score([self.project]) == {self.project.pk: self.newest}
        assert self.newest.reason == "Lint errored"

    def test_not_when_the_newest_commit_has_a_verdict(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)

        assert scoring.newest_without_score([self.project]) == {}

    def test_rechecking_an_old_commit_with_no_score_does_not_flag_the_newest(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)
        self._commit("0" * 40, timezone.now() - timedelta(days=5), Status.ERROR)

        assert scoring.newest_without_score([self.project]) == {}

    def test_another_branch_does_not_count(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)
        self._commit("4" * 40, timezone.now() + timedelta(hours=2), Status.ERROR, branch="feature")

        assert scoring.newest_without_score([self.project]) == {}

    def test_a_project_with_no_verdict_at_all_is_flagged_too(self):
        other = baker.make("app.Project", tenant=self.tenant, name="Web", default_branch="main", languages=[])
        self._standard("Lint", project=other)
        without = self._commit("5" * 40, timezone.now(), Status.ERROR, project=other)

        assert scoring.newest_without_score([self.project, other]) == {
            self.project.pk: self.newest, other.pk: without,
        }

    def test_nothing_to_read(self):
        assert scoring.newest_without_score([]) == {}


class CountsTests(Fixture):
    def test_counted_projects_carry_their_newest_without_score(self):
        counts = ProjectHealthCounts.of([self.project])

        assert counts.healthy == 1
        [(project, score)] = counts.healthy_projects
        assert (project.newest_without_score, score) == (self.newest, self.verdict)
        assert counts.older_commit_names == ["Backend"]


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class PagesTests(Fixture):
    def test_the_project_card_says_it_shows_an_older_commit(self):
        body = self.client.get(reverse("project_list")).content.decode()

        assert "data-older-commit" in body
        assert "Not the latest commit: showing 1111111. The newest, 2222222, has no score (Lint errored)." in body

    def test_a_project_card_with_a_latest_score_says_nothing(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)

        assert "data-older-commit" not in self.client.get(reverse("project_list")).content.decode()

    def test_the_overview_warns_and_links_to_the_results(self):
        body = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()

        assert "data-older-commit-alert" in body
        assert "This score is from commit 1111111." in body
        assert "The newest commit, 2222222, has no score: Lint errored." in body
        assert 'data-open-tab="results">See results' in body

    def test_the_results_tab_warns_and_offers_to_run_the_newest_again(self):
        body = self.client.get(reverse("project_history", args=[self.project.pk]), HTTP_HX_REQUEST="true").content.decode()

        assert "data-older-commit-alert" in body
        assert "data-older-commit-run" in body
        assert f'"sha": "{NEW}"' in body

    def test_a_newer_commit_still_checking_gets_the_small_note_not_the_warning(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)
        check = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha="4" * 40,
            committed_at=timezone.now() + timedelta(hours=2), expected_standard_ids=[str(self.lint.pk)],
        )
        baker.make("app.StandardExecution", project=self.project, standard=self.lint, commit_check=check, status=Status.RUNNING)

        body = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()

        assert 'data-newer-commit="checking"' in body
        assert "data-older-commit-alert" not in body

    def _dashboard(self):
        # The dashboard shows its map, counts and Needs attention once the
        # workspace has a stack.
        baker.make("app.Stack", tenant=self.tenant, name="Core").components.add(self._component())
        return self.client.get(reverse("dashboard")).content.decode()

    def test_the_dashboard_counts_flag_it_and_its_hover_row_says_why(self):
        body = self._dashboard()

        assert "data-older-commit-count" in body
        assert "<b>1</b> not the latest commit" in body
        assert 'title="Not the latest commit: showing 1111111. The newest, 2222222, has no score (Lint errored)."' in body

    def test_a_stack_card_flags_it(self):
        stack = baker.make("app.Stack", tenant=self.tenant, name="Core")
        stack.components.add(self._component())

        body = self.client.get(reverse("stack_list")).content.decode()

        assert "data-older-commit-count" in body
        assert "the newest commit of Backend has no score" in body

    def test_needs_attention_explains_what_it_lists(self):
        body = self._dashboard()

        assert "data-attention-help" in body
        assert "Only failed projects (a Required standard failed) and standard runs that errored" in body


class MapTests(Fixture):
    def setUp(self):
        super().setUp()
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Core")
        self.stack.components.add(self._component())

    def test_the_stack_node_names_the_project_showing_an_older_commit(self):
        [node] = [n for n in workspace_graph(self.tenant)["stacks"] if n["name"] == "Core"]

        assert "Backend — Not the latest commit: showing 1111111. The newest, 2222222, has no score (Lint errored)." in node["issues"]

    def test_the_component_node_says_it_first(self):
        graph = stack_graph(self.stack)
        [node] = [n for n in graph["components"] if n["name"] == "api"]

        assert node["issues"][0].startswith("Not the latest commit: showing 1111111.")


class StatusAPITests(Fixture):
    def test_status_says_a_newer_commit_has_no_score(self):
        status = ProjectStatusService().get_project_status(self.tenant, str(self.project.pk))

        assert status["commit_sha"] == OLD
        assert status["newer_commit"] == {
            "sha": NEW, "outcome": "no_score", "reason": "Lint errored", "standards": {"expected": 2, "finished": 2},
        }
