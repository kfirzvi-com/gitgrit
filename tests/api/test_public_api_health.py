"""Health and commit checks over the public API: the project page's Health
card, as data."""
from unittest import mock

from model_bakery import baker

from app.application import commit_checks
from app.domain.models import CommitCheck, StandardExecution
from tests.api.test_public_api import PublicAPITestCase, make_oauth_token

Status = StandardExecution.Status
A, B, C = "a" * 40, "b" * 40, "c" * 40


class HealthAPITestCase(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.project = baker.make(
            "app.Project", tenant=self.tenant, name="backend", default_branch="main", languages=[]
        )
        self.standard = baker.make(
            "app.Standard", tenant=self.tenant, name="Pinned CI", enabled=True, draft=False,
            criteria={"events": ["push"], "languages": []},
        )
        self.project.standards.add(self.standard)
        self.platform = mock.Mock()
        self.platform.list_branches.return_value = ["feature/x", "main"]
        self.platform.list_commits.return_value = [
            {"sha": A, "message": "Fix CI\n\nbody", "author": "Dana",
             "date": "2026-10-01T10:00:00Z", "url": "https://git.example/a"},
            {"sha": B, "message": "Unchecked", "author": "Dana",
             "date": "2026-09-30T10:00:00Z", "url": ""},
        ]
        self.platform.head_commit.return_value = {}
        for patch in (
            mock.patch.object(commit_checks, "_client", return_value=self.platform),
            mock.patch("app.application.standard_runs.run_standards.configure"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.p = f"{self.ws}/projects/{self.project.id}"

    def check(self, sha, branch="main", status=Status.PASSED, score=100):
        check = baker.make(
            "app.CommitCheck", project=self.project, branch=branch, commit_sha=sha
        )
        return baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=status, score=score, commit_check=check,
            ref=branch,
        )


class TestBranchesAndHealth(HealthAPITestCase):
    def test_branches_default_first(self):
        r = self.get(f"{self.p}/branches/")
        assert r.status_code == 200
        assert r.json() == [
            {"name": "main", "is_default": True},
            {"name": "feature/x", "is_default": False},
        ]

    def test_project_health_has_grade_reason_and_level_and_keeps_score(self):
        self.check(A, status=Status.FAILED, score=40)
        r = self.get(f"{self.p}/health/")
        assert r.status_code == 200
        body = r.json()
        assert (body["branch"], body["score"], body["level"]) == (None, 40, "attention")
        assert (body["grade"], body["reason"]) == ("D", "1 standard failing")
        assert (body["passed"], body["failed"], body["errored"]) == (0, 1, 0)
        assert body["results"][0]["commit_sha"] == A
        assert body["results"][0]["standard_name"] == "Pinned CI"

    def test_a_failing_critical_standard_is_f_and_failing(self):
        self.project.project_standards.update(critical=True)
        self.check(A, status=Status.FAILED, score=40)
        body = self.get(f"{self.p}/health/").json()
        assert (body["grade"], body["reason"], body["level"]) == ("F", "Pinned CI failing", "failing")

    def test_a_branch_does_not_move_project_health_but_has_its_own(self):
        self.check(A, branch="main", score=100)
        self.check(C, branch="feature/x", status=Status.FAILED, score=10)
        project = self.get(f"{self.p}/health/").json()
        assert (project["grade"], project["level"]) == ("A+", "good")
        branch = self.get(f"{self.p}/health/", branch="feature/x").json()
        assert (branch["branch"], branch["score"], branch["level"]) == ("feature/x", 10, "attention")
        assert branch["grade"] == "D"

    def test_no_results_is_unknown(self):
        body = self.get(f"{self.p}/health/").json()
        assert (body["score"], body["grade"], body["level"]) == (None, None, "unknown")
        assert (body["reason"], body["results"]) == ("no results yet", [])

    def test_foreign_project_is_404(self):
        foreign = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        assert self.get(f"{self.ws}/projects/{foreign.id}/health/").status_code == 404


class TestCommits(HealthAPITestCase):
    def test_commits_page(self):
        self.check(A, status=Status.FAILED, score=60)
        r = self.get(f"{self.p}/commits/")
        assert r.status_code == 200
        body = r.json()
        assert (body["branch"], body["page"], body["has_more"]) == ("main", 1, False)
        checked, unchecked = body["commits"]
        assert (checked["sha"], checked["title"], checked["checked"]) == (A, "Fix CI", True)
        assert (checked["score"], checked["level"], checked["failed"]) == (60, "attention", 1)
        assert (checked["grade"], checked["reason"]) == ("D", "1 standard failing")
        assert (unchecked["grade"], unchecked["level"]) == (None, "unknown")
        assert checked["results"][0]["still_attached"] is True
        assert (unchecked["checked"], unchecked["results"]) == (False, [])

    def test_commits_fall_back_to_recorded_checks_when_platform_is_down(self):
        self.platform.list_commits.side_effect = RuntimeError("down")
        self.check(A)
        commits = self.get(f"{self.p}/commits/").json()["commits"]
        assert [c["sha"] for c in commits] == [A]

    def test_bad_page(self):
        assert self.get(f"{self.p}/commits/", page="x").status_code == 400

    def test_one_commit(self):
        self.check(A, status=Status.RUNNING, score=0)
        r = self.get(f"{self.p}/commits/{A}/")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] == 1
        assert (body["grade"], body["level"]) == (None, "unknown")
        assert body["results"][0]["status"] == "running"
        assert body["results"][0]["score"] is None

    def test_a_commit_is_graded_as_it_was_marked_when_it_ran(self):
        # The standard was critical when the commit ran and is not any more:
        # the commit's verdict reads its snapshot, the project's its mark.
        ex = self.check(A, status=Status.FAILED, score=40)
        StandardExecution.objects.filter(pk=ex.pk).update(critical=True)
        commit = self.get(f"{self.p}/commits/{A}/").json()
        project = self.get(f"{self.p}/health/").json()
        assert (commit["grade"], commit["reason"]) == ("F", "Pinned CI failing")
        assert project["grade"] == "D"

    def test_unchecked_commit_is_404(self):
        assert self.get(f"{self.p}/commits/{B}/").status_code == 404


class TestRunCheck(HealthAPITestCase):
    def test_check_a_commit(self):
        r = self.send("post", f"{self.p}/checks/", {"branch": "main", "sha": A})
        assert r.status_code == 202, r.content
        body = r.json()
        assert (body["branch"], body["commit_sha"], body["queued"]) == ("main", A, 1)
        assert body["message"] == "Running 1 standard on aaaaaaa."
        check = CommitCheck.objects.get()
        assert (check.branch, check.commit_sha) == ("main", A)

    def test_check_the_default_branch_head(self):
        self.platform.head_commit.return_value = {"sha": C, "date": "2026-10-02T10:00:00Z"}
        body = self.send("post", f"{self.p}/checks/").json()
        assert (body["branch"], body["commit_sha"]) == ("main", C)
        assert "the latest commit on main" in body["message"]

    def test_unresolvable_head_still_queues(self):
        body = self.send("post", f"{self.p}/checks/", {"branch": "main"}).json()
        assert (body["commit_sha"], body["queued"]) == (None, 1)

    def test_nothing_applies(self):
        self.standard.criteria = {"events": ["push"], "languages": [], "ref": "^develop$"}
        self.standard.save()
        body = self.send("post", f"{self.p}/checks/", {"branch": "main"}).json()
        assert (body["queued"], body["message"]) == (0, "No standards apply to main.")

    def test_bad_sha(self):
        r = self.send("post", f"{self.p}/checks/", {"sha": "not-a-sha"})
        assert r.status_code == 400

    def test_needs_write_scope(self):
        self.auth = {"Authorization": f"Bearer {make_oauth_token(self.user, scope='read')}"}
        assert self.send("post", f"{self.p}/checks/").status_code == 403
        assert self.get(f"{self.p}/health/").status_code == 200


def test_serializer_choices_come_from_the_grading_constants():
    from app.domain import grading
    from app.presentation.api import serializers as s

    assert s.GRADE_CHOICES == ["A+", "A", "B", "C", "D", "F"]
    assert set(s.GRADE_CHOICES) == set(grading.LETTER_ORDER)
    assert s.LEVEL_CHOICES == [
        grading.TONE_GOOD, grading.TONE_ATTENTION, grading.TONE_FAILING, grading.TONE_UNKNOWN,
    ]
    assert {grading.tone_for(letter) for letter in grading.LETTER_ORDER} <= set(s.LEVEL_CHOICES)
