"""Webhook events carry the commit they are about."""
from django.test import SimpleTestCase

from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser


class GitHubCommitTests(SimpleTestCase):
    def test_a_push_is_about_its_new_head(self):
        event = GitHubParser().parse(
            {"x-github-event": "push"},
            {"ref": "refs/heads/main", "after": "a" * 40, "repository": {"id": 1}, "sender": {}},
        )
        self.assertEqual(event.commit_sha, "a" * 40)

    def test_a_pull_request_is_about_its_head_commit(self):
        event = GitHubParser().parse(
            {"x-github-event": "pull_request"},
            {
                "pull_request": {"head": {"ref": "feature/x", "sha": "b" * 40}, "base": {"ref": "main"}},
                "repository": {"id": 1}, "sender": {},
            },
        )
        self.assertEqual((event.ref, event.commit_sha), ("feature/x", "b" * 40))


class GitLabCommitTests(SimpleTestCase):
    def test_a_push_is_about_its_checkout_sha(self):
        event = GitLabParser().parse(
            {}, {"object_kind": "push", "ref": "refs/heads/main", "project_id": 7, "checkout_sha": "c" * 40, "after": "c" * 40}
        )
        self.assertEqual(event.commit_sha, "c" * 40)

    def test_a_merge_request_is_about_its_last_commit(self):
        event = GitLabParser().parse(
            {},
            {
                "object_kind": "merge_request", "project_id": 7,
                "object_attributes": {"source_branch": "feature/x", "target_branch": "main", "last_commit": {"id": "d" * 40}},
            },
        )
        self.assertEqual(event.commit_sha, "d" * 40)


class CommitDateTests(SimpleTestCase):
    def test_a_github_push_carries_its_commit_date(self):
        event = GitHubParser().parse(
            {"x-github-event": "push"},
            {"ref": "refs/heads/main", "after": "a" * 40, "head_commit": {"timestamp": "2026-10-01T10:00:00Z"},
             "repository": {"id": 1}, "sender": {}},
        )
        self.assertEqual(event.committed_at, "2026-10-01T10:00:00Z")

    def test_a_gitlab_push_carries_its_head_commits_date(self):
        event = GitLabParser().parse({}, {
            "object_kind": "push", "ref": "refs/heads/main", "project_id": 7, "checkout_sha": "c" * 40,
            "commits": [{"id": "b" * 40, "timestamp": "old"}, {"id": "c" * 40, "timestamp": "2026-10-01T10:00:00Z"}],
        })
        self.assertEqual(event.committed_at, "2026-10-01T10:00:00Z")
