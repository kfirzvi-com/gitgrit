"""Listing a repository's branches and commits, and a branch's head commit."""
from unittest import mock

from django.test import SimpleTestCase
from model_bakery import baker

from app.infrastructure.platform_client import GitHubClient, GitLabClient


def _response(payload):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class _ClientTestCase(SimpleTestCase):
    platform_client = None
    platform = None

    def setUp(self):
        connection = baker.prepare(
            "app.PlatformConnection", platform=self.platform, auth_method="pat",
            base_url="https://git.example.test", access_token="tok",
        )
        self.client_ = self.platform_client(connection)
        patch = mock.patch("app.infrastructure.platform_client.requests.get")
        self.get = patch.start()
        self.addCleanup(patch.stop)


class GitHubHistoryTests(_ClientTestCase):
    platform_client, platform = GitHubClient, "github"

    def test_branches(self):
        self.get.return_value = _response([{"name": "main"}, {"name": "feature/x"}])
        self.assertEqual(self.client_.list_branches("1", "acme/repo"), ["main", "feature/x"])
        self.assertIn("/repos/acme/repo/branches", self.get.call_args.args[0])

    def test_commits(self):
        self.get.return_value = _response([{
            "sha": "a" * 40, "html_url": "https://github.test/c/a",
            "commit": {"message": "Fix it\n\nbody", "author": {"name": "Dana", "date": "2026-10-01T10:00:00Z"}},
        }])

        [commit] = self.client_.list_commits("1", "acme/repo", "feature/x", page=2, per_page=5)

        self.assertEqual(commit, {
            "sha": "a" * 40, "message": "Fix it\n\nbody", "author": "Dana",
            "date": "2026-10-01T10:00:00Z", "url": "https://github.test/c/a",
        })
        self.assertEqual(self.get.call_args.kwargs["params"], {"sha": "feature/x", "page": 2, "per_page": 5})

    def test_head_commit_quotes_the_branch(self):
        self.get.return_value = _response(
            {"sha": "b" * 40, "commit": {"author": {"date": "2026-10-02T09:00:00Z"}}}
        )
        self.assertEqual(
            self.client_.head_commit("1", "acme/repo", "feature/x"),
            {"sha": "b" * 40, "date": "2026-10-02T09:00:00Z"},
        )
        self.assertTrue(self.get.call_args.args[0].endswith("/repos/acme/repo/commits/feature%2Fx"))


class GitLabHistoryTests(_ClientTestCase):
    platform_client, platform = GitLabClient, "gitlab"

    def test_branches(self):
        self.get.return_value = _response([{"name": "main"}])
        self.assertEqual(self.client_.list_branches("7", "acme/repo"), ["main"])
        self.assertIn("/projects/7/repository/branches", self.get.call_args.args[0])

    def test_commits(self):
        self.get.return_value = _response([{
            "id": "c" * 40, "message": "Fix it", "author_name": "Sam",
            "committed_date": "2026-10-01T10:00:00Z", "web_url": "https://gitlab.test/c/c",
        }])

        [commit] = self.client_.list_commits("7", "acme/repo", "main")

        self.assertEqual(commit["sha"], "c" * 40)
        self.assertEqual(commit["author"], "Sam")
        self.assertEqual(self.get.call_args.kwargs["params"]["ref_name"], "main")

    def test_head_commit(self):
        self.get.return_value = _response({"commit": {"id": "d" * 40, "committed_date": "2026-10-02T09:00:00Z"}})
        self.assertEqual(
            self.client_.head_commit("7", "acme/repo", "feature/x"),
            {"sha": "d" * 40, "date": "2026-10-02T09:00:00Z"},
        )
        self.assertTrue(self.get.call_args.args[0].endswith("/repository/branches/feature%2Fx"))
