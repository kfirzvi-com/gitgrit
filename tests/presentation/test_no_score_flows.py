"""Every place a project's score shows reads its default branch's newest
commit, and says why there is no grade: the commit is still being checked,
or it has no score (a standard errored or never ran in its newest run). And
"Needs attention" explains what it lists."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application import scoring
from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution
from app.presentation.architecture import stack_graph, workspace_graph
from app.presentation.no_score_note import NoScoreNote

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
Status = StandardExecution.Status
OLD, NEW = "1" * 40, "2" * 40


class NoScoreNoteTests(SimpleTestCase):
    def test_a_commit_score_with_no_score_says_why(self):
        score = baker.prepare("app.CommitScore", commit_sha=NEW, reason="Lint errored")
        assert NoScoreNote.text(score) == "No score on commit 2222222: Lint errored."

    def test_with_no_reason_on_record(self):
        score = baker.prepare("app.CommitScore", commit_sha=NEW, reason="")
        assert NoScoreNote.text(score) == "No score on commit 2222222: not every standard has a result."

    def test_a_verdict_or_nothing_says_nothing(self):
        assert NoScoreNote.text(baker.prepare("app.CommitScore", commit_sha=NEW, value=80)) == ""
        assert NoScoreNote.text(baker.prepare("app.CommitScore", commit_sha=NEW, failed=True)) == ""
        assert NoScoreNote.text(None) == ""


class Fixture(TestCase):
    """A project whose newest commit has no score because a standard errored
    (its older commit was scored)."""

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
        self._commit(OLD, now - timedelta(days=1), Status.PASSED)
        self.newest = self._commit(NEW, now, Status.ERROR)

    def _component(self):
        """The project's own component (every project has one at its root)."""
        component = self.project.components.first() or baker.make(
            "app.Component", tenant=self.tenant, project=self.project, name="api"
        )
        component.name = "api"
        component.save()
        return component

    def _standard(self, name):
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, enabled=True, draft=False, criteria={})
        self.project.standards.add(standard)
        return standard

    def _commit(self, sha, committed_at, lint_status, running=False):
        standards = list(self.project.standards.all())
        check = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha=sha, committed_at=committed_at,
            expected_standard_ids=[str(s.pk) for s in standards],
        )
        for s in standards:
            status = lint_status if s.name == "Lint" else Status.PASSED
            baker.make(
                "app.StandardExecution", project=self.project, standard=s, standard_name=s.name, commit_check=check,
                status=Status.RUNNING if running and s.name == "Lint" else status, score=100, ref="main",
            )
        return scoring.score_check(check)

    def _dashboard(self):
        # The dashboard shows its map, counts and Needs attention once the
        # workspace has a stack.
        baker.make("app.Stack", tenant=self.tenant, name="Core").components.add(self._component())
        return self.client.get(reverse("dashboard")).content.decode()


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class PagesTests(Fixture):
    def test_the_project_card_has_no_grade_and_says_why(self):
        body = self.client.get(reverse("project_list")).content.decode()

        assert 'data-no-score-note="no_score"' in body
        assert "No score on commit 2222222: Lint errored." in body

    def test_the_project_card_says_its_newest_commit_is_being_checked(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED, running=True)

        body = self.client.get(reverse("project_list")).content.decode()

        assert 'data-no-score-note="checking"' in body
        assert "Checking commit 3333333: 1 of 2 standards done…" in body

    def test_a_scored_project_card_says_nothing_more(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED)

        assert "data-no-score-note" not in self.client.get(reverse("project_list")).content.decode()

    def test_the_overview_warns_and_links_to_the_results(self):
        body = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()

        assert "gg-tone-card-unknown" in body
        assert "data-no-score-alert" in body
        assert "The newest commit, 2222222, has no score: Lint errored." in body
        assert 'data-open-tab="results">See results' in body

    def test_the_results_tab_warns_and_offers_to_run_it_again(self):
        body = self.client.get(reverse("project_history", args=[self.project.pk]), HTTP_HX_REQUEST="true").content.decode()

        assert "data-no-score-alert" in body
        assert "data-no-score-run" in body
        assert f'"sha": "{NEW}"' in body

    def test_while_checking_the_tabs_say_so_instead_of_warning(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED, running=True)

        body = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()

        assert "data-checking-commit" in body
        assert "Checking commit 3333333: 1 of 2 standards done…" in body
        assert "data-no-score-alert" not in body

    def test_the_dashboard_counts_it_as_no_data_and_its_hover_row_says_why(self):
        body = self._dashboard()

        assert '<b>1</b> no data' in body
        assert 'title="No score on commit 2222222: Lint errored."' in body

    def test_needs_attention_explains_what_it_lists(self):
        body = self._dashboard()

        assert "data-attention-help" in body
        assert "Only failed projects (a Required standard failed) and standard runs that errored" in body


class MapTests(Fixture):
    def setUp(self):
        super().setUp()
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Core")
        self.stack.components.add(self._component())

    def test_the_stack_node_names_the_project_with_no_score_and_why(self):
        [node] = [n for n in workspace_graph(self.tenant)["stacks"] if n["name"] == "Core"]

        assert "Backend — No score on commit 2222222: Lint errored." in node["issues"]

    def test_the_component_node_says_why(self):
        [node] = [n for n in stack_graph(self.stack)["components"] if n["name"] == "api"]

        assert node["issues"] == ["No score on commit 2222222: Lint errored."]


class StatusAPITests(Fixture):
    def test_status_reads_the_newest_commit(self):
        status = ProjectStatusService().get_project_status(self.tenant, str(self.project.pk))

        assert (status["commit_sha"], status["outcome"], status["reason"], status["overall_score"]) == (
            NEW, "no_score", "Lint errored", None
        )
        assert "newer_commit" not in status

    def test_status_while_checking(self):
        self._commit("3" * 40, timezone.now() + timedelta(hours=1), Status.PASSED, running=True)

        status = ProjectStatusService().get_project_status(self.tenant, str(self.project.pk))

        assert (status["outcome"], status["overall_score"], status["commit_sha"]) == ("checking", None, None)
