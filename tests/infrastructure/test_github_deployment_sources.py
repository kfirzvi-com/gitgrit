"""The GitHub deployment sources, against canned API answers: which records
count as production deployments, when, and whether they shipped."""
from datetime import datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from app.application.delivery import SourceUnavailable
from app.domain.delivery import DeploymentStrategy, ProductionEnvironment
from app.infrastructure.delivery.github_branch_pushes import GitHubBranchPushes
from app.infrastructure.delivery.github_environment_deployments import GitHubEnvironmentDeployments
from app.infrastructure.delivery.github_release_tags import GitHubReleaseTags
from app.infrastructure.delivery.github_workflow_runs import GitHubWorkflowRuns

SINCE = datetime(2026, 11, 1, tzinfo=timezone.utc)


class FakeApi:
    def __init__(self, lists=None, objects=None):
        self.lists = lists or {}
        self.objects = objects or {}
        self.calls = []

    def pages(self, path, params=None, permission="Contents", key=""):
        self.calls.append((path, params))
        yield from self.lists.get(path, [])

    def get(self, path, params=None, permission="Contents"):
        self.calls.append((path, params))
        return self.objects[path]


def status(state, at):
    return {"state": state, "created_at": at}


class EnvironmentDeploymentsTests(SimpleTestCase):
    def find(self, deployments, statuses):
        api = FakeApi({"deployments": deployments}, {f"deployments/{i}/statuses": s for i, s in statuses.items()})
        return GitHubEnvironmentDeployments(api, ProductionEnvironment()).find(SINCE)

    def deployment(self, id, environment="production", created="2026-11-10T10:00:00Z"):
        return {"id": id, "environment": environment, "sha": f"sha{id}", "ref": "main", "created_at": created}

    def test_a_deployment_counts_when_it_first_succeeded(self):
        events = self.find(
            [self.deployment(1)],
            # newest first, as GitHub lists them: superseded after succeeding
            {1: [status("inactive", "2026-11-11T00:00:00Z"), status("success", "2026-11-10T10:05:00Z"),
                 status("in_progress", "2026-11-10T10:01:00Z")]},
        )

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].succeeded)
        self.assertEqual(events[0].deployed_at, datetime(2026, 11, 10, 10, 5, tzinfo=timezone.utc))

    def test_failed_ones_count_as_failed_and_running_ones_wait(self):
        events = self.find(
            [self.deployment(1), self.deployment(2)],
            {1: [status("failure", "2026-11-10T10:05:00Z")], 2: [status("in_progress", "2026-11-10T10:01:00Z")]},
        )

        self.assertEqual([(e.external_id, e.succeeded) for e in events], [("1", False)])

    def test_only_production_environments_count_and_old_ones_stop_the_walk(self):
        events = self.find(
            [self.deployment(1, "staging"), self.deployment(2, "prod-eu"), self.deployment(3, created="2026-10-01T00:00:00Z")],
            {2: [status("success", "2026-11-10T10:05:00Z")]},
        )

        self.assertEqual([e.environment for e in events], ["prod-eu"])


class ReleaseTagsTests(SimpleTestCase):
    def test_tags_matching_the_pattern_date_from_their_release_or_commit(self):
        api = FakeApi(
            {
                "releases": [
                    {"tag_name": "v1.1.0", "draft": False, "prerelease": False, "published_at": "2026-11-12T09:00:00Z"},
                    {"tag_name": "v1.2.0-rc1", "draft": False, "prerelease": True, "published_at": "2026-11-13T09:00:00Z"},
                ],
                "tags": [
                    {"name": "v1.2.0-rc1", "commit": {"sha": "rc"}},
                    {"name": "v1.1.0", "commit": {"sha": "b"}},
                    {"name": "v1.0.0", "commit": {"sha": "a"}},
                    {"name": "nightly", "commit": {"sha": "n"}},
                    {"name": "v0.9.0", "commit": {"sha": "old"}},
                ],
            },
            {
                "commits/a": {"commit": {"committer": {"date": "2026-11-05T09:00:00Z"}}},
                "commits/old": {"commit": {"committer": {"date": "2026-09-01T09:00:00Z"}}},
            },
        )

        events = GitHubReleaseTags(api, "v*").find(SINCE)

        self.assertEqual([(e.ref, e.deployed_at.day) for e in events], [("v1.1.0", 12), ("v1.0.0", 5)])


class WorkflowRunsTests(SimpleTestCase):
    def test_completed_runs_count_but_cancelled_ones_do_not(self):
        path = "actions/workflows/deploy.yml/runs"
        runs = [
            {"id": 1, "conclusion": "success", "head_sha": "a", "updated_at": "2026-11-10T10:00:00Z"},
            {"id": 2, "conclusion": "failure", "head_sha": "b", "updated_at": "2026-11-11T10:00:00Z"},
            {"id": 3, "conclusion": "cancelled", "head_sha": "c", "updated_at": "2026-11-12T10:00:00Z"},
        ]
        api = FakeApi({path: runs})

        events = GitHubWorkflowRuns(api, ".github/workflows/deploy.yml", "main").find(SINCE)

        self.assertEqual([(e.external_id, e.succeeded) for e in events], [("1", True), ("2", False)])
        self.assertEqual(api.calls[0][1]["branch"], "main")

    def test_the_workflow_must_be_named(self):
        with self.assertRaises(SourceUnavailable):
            GitHubWorkflowRuns(FakeApi(), "", "main").find(SINCE)


class BranchPushesTests(SimpleTestCase):
    def test_each_push_or_merge_to_the_branch_is_a_deployment(self):
        activity = [
            {"id": 4, "activity_type": "push", "after": "d", "timestamp": "2026-11-12T10:00:00Z"},
            {"id": 3, "activity_type": "pr_merge", "after": "c", "timestamp": "2026-11-11T10:00:00Z"},
            {"id": 2, "activity_type": "branch_creation", "after": "b", "timestamp": "2026-11-10T10:00:00Z"},
            {"id": 1, "activity_type": "push", "after": "a", "timestamp": "2026-10-01T10:00:00Z"},
        ]
        api = FakeApi({"activity": activity})

        events = GitHubBranchPushes(api, DeploymentStrategy.DEPLOY_BRANCH, "production").find(SINCE)

        self.assertEqual([e.sha for e in events], ["d", "c"])
        self.assertEqual(api.calls[0][1]["ref"], "refs/heads/production")


class RepositoryActivityTests(SimpleTestCase):
    def test_pending_commits_count_what_the_branch_has_beyond_the_deployed_commit(self):
        from app.infrastructure.delivery.github_repository_activity import GitHubRepositoryActivity

        api = mock.Mock()
        api.get.return_value = {"ahead_by": 2, "oldest": "2026-11-20T09:00:00Z"}

        pending = GitHubRepositoryActivity(api).pending_commits("abc", "main")

        self.assertEqual(pending.count, 2)
        self.assertEqual(pending.oldest_at, datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
        self.assertEqual(api.get.call_args.args[0], "compare/abc...main")

    def test_a_deployed_commit_gone_from_the_repository_is_not_known(self):
        import requests

        from app.infrastructure.delivery.github_repository_activity import GitHubRepositoryActivity

        api = mock.Mock()
        api.get.side_effect = requests.HTTPError(response=mock.Mock(status_code=404))

        self.assertIsNone(GitHubRepositoryActivity(api).pending_commits("gone", "main"))

    def test_the_compare_answer_is_slimmed_to_count_and_oldest(self):
        from app.infrastructure.delivery.github_repository_activity import _slim_compare

        slim = _slim_compare({"ahead_by": 2, "files": [1, 2], "commits": [
            {"commit": {"committer": {"date": "2026-11-20T09:00:00Z"}}},
            {"commit": {"committer": {"date": "2026-11-21T09:00:00Z"}}},
        ]})

        self.assertEqual(slim, {"ahead_by": 2, "oldest": "2026-11-20T09:00:00Z"})
