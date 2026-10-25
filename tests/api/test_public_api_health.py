"""Health and commit checks over the public API: the project page's Health
card, as data."""
from unittest import mock

from model_bakery import baker

from app.application import commit_checks
from app.domain.models import CommitCheck, StandardExecution
from tests.api.test_public_api import PublicAPITestCase, make_oauth_token
from tests.support import score_commit

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
        """One finished result on ``sha``, scored the way a finished check is."""
        check = baker.make(
            "app.CommitCheck", project=self.project, branch=branch, commit_sha=sha,
            expected_standard_ids=[str(self.standard.pk)],
        )
        execution = baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=status, score=score, commit_check=check,
            ref=branch,
        )
        if status != Status.RUNNING:
            score_commit(self.project, sha, branch=branch)
        return execution


class TestBranchesAndHealth(HealthAPITestCase):
    def test_branches_default_first(self):
        r = self.get(f"{self.p}/branches/")
        assert r.status_code == 200
        assert r.json() == [
            {"name": "main", "is_default": True},
            {"name": "feature/x", "is_default": False},
        ]

    def test_project_health(self):
        self.check(A, status=Status.FAILED, score=40)
        r = self.get(f"{self.p}/health/")
        assert r.status_code == 200
        body = r.json()
        assert (body["branch"], body["score"]) == (None, 40)
        assert "level" not in body
        assert (body["passed"], body["failed"], body["errored"]) == (0, 1, 0)
        assert body["results"][0]["commit_sha"] == A
        assert body["results"][0]["standard_name"] == "Pinned CI"
        assert body["score_display"] == {"text": "D", "tone": "needs_attention", "spoken": "Grade D, score 40 out of 100"}
        assert body["commit_score"] == {
            "outcome": "scored", "value": 40, "reason": "",
            "display": {"text": "D", "tone": "needs_attention", "spoken": "Grade D, score 40 out of 100"},
            "standards": {"expected": 1, "finished": 1},
            "commit": {"sha": A, "branch": "main", "committed_at": None},
        }
        assert "newer_commit" not in body

    def test_a_failing_required_standard_fails_the_project_with_no_score(self):
        self.project.project_standards.update(importance="required")
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=A)
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=Status.FAILED, score=90, commit_check=check,
            importance="required",
        )
        score_commit(self.project, A)

        body = self.get(f"{self.p}/health/").json()

        assert (body["score"], body["score_display"]["tone"]) == (None, "failed")
        assert (body["commit_score"]["value"], body["commit_score"]["outcome"]) == (None, "failed")
        assert "failed" not in body["commit_score"] and "state" not in body["commit_score"]
        assert body["commit_score"]["display"] == {"text": "F", "tone": "failed", "spoken": body["commit_score"]["display"]["spoken"]}
        assert body["commit_score"]["reason"] == "Pinned CI failing"

    def test_the_newest_commit_still_checking_has_no_score_yet(self):
        self.check(A, status=Status.PASSED, score=100)
        running = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha=C,
            expected_standard_ids=[str(self.standard.pk)],
        )
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=Status.RUNNING, score=0, commit_check=running,
        )

        body = self.get(f"{self.p}/health/").json()

        assert (body["score"], body["score_display"]["text"]) == (None, "—")
        assert body["commit_score"]["commit"]["sha"] == C
        assert (body["commit_score"]["outcome"], body["commit_score"]["standards"]) == (
            "checking", {"expected": 1, "finished": 0}
        )

    def test_the_newest_commit_with_no_score_is_the_projects_and_says_why(self):
        self.check(A, status=Status.PASSED, score=100)
        self.check(C, status=Status.ERROR, score=0)

        body = self.get(f"{self.p}/health/").json()

        assert (body["score"], body["score_display"]["text"]) == (None, "—")
        assert (body["commit_score"]["commit"]["sha"], body["commit_score"]["outcome"], body["commit_score"]["reason"]) == (
            C, "no_score", "Pinned CI errored"
        )
        assert [r["status"] for r in body["results"]] == ["error"]

    def test_a_branch_does_not_move_project_health_but_has_its_own(self):
        self.check(A, branch="main", score=100)
        self.check(C, branch="feature/x", status=Status.FAILED, score=10)
        assert self.get(f"{self.p}/health/").json()["score_display"]["tone"] == "healthy"
        branch = self.get(f"{self.p}/health/", branch="feature/x").json()
        assert (branch["branch"], branch["score"], branch["score_display"]["tone"]) == ("feature/x", 10, "needs_attention")

    def test_no_results_is_unknown(self):
        body = self.get(f"{self.p}/health/").json()
        assert (body["score"], body["score_display"]["tone"], body["results"]) == (None, "unknown", [])
        assert body["commit_score"] is None

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
        assert (checked["score"], checked["failed"]) == (60, 1)
        assert "level" not in checked
        assert (checked["commit_score"]["outcome"], checked["commit_score"]["value"]) == ("scored", 60)
        assert checked["results"][0]["still_attached"] is True
        assert unchecked["commit_score"] is None
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
        assert body["results"][0]["status"] == "running"
        assert body["results"][0]["score"] is None
        assert (body["commit_score"]["outcome"], body["commit_score"]["value"]) == ("checking", None)
        assert body["commit_score"]["display"]["text"] == "—"

    def test_one_commit_with_no_score_says_why(self):
        self.check(A, status=Status.ERROR, score=0)

        commit_score = self.get(f"{self.p}/commits/{A}/").json()["commit_score"]

        assert (commit_score["outcome"], commit_score["value"], commit_score["reason"]) == (
            "no_score", None, "Pinned CI errored"
        )

    def test_one_failed_commit_reads_f(self):
        self.project.project_standards.update(importance="required")
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=A)
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="Pinned CI", status=Status.FAILED, score=90, commit_check=check,
            importance="required",
        )
        score_commit(self.project, A)

        commit_score = self.get(f"{self.p}/commits/{A}/").json()["commit_score"]

        assert (commit_score["outcome"], commit_score["value"], commit_score["display"]["text"]) == ("failed", None, "F")
        assert commit_score["reason"] == "Pinned CI failing"

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
