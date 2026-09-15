"""Webhook events carry the commit they are about, so the grade can be posted
back to it as a commit status. GitHub: the pushed head or the PR head. A
branch delete pushes the all-zeros SHA and has no commit. GitLab: none yet."""
from django.test import SimpleTestCase

from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser

SHA = "a" * 40


class GitHubCommitShaTests(SimpleTestCase):
    def test_push_uses_after(self):
        event = GitHubParser().parse(
            {"x-github-event": "push"},
            {"ref": "refs/heads/main", "after": SHA, "repository": {"id": 1}, "sender": {}},
        )
        assert event.commit_sha == SHA

    def test_branch_delete_has_no_commit(self):
        event = GitHubParser().parse(
            {"x-github-event": "push"},
            {
                "ref": "refs/heads/old",
                "after": "0" * 40,
                "deleted": True,
                "repository": {"id": 1},
                "sender": {},
            },
        )
        assert event.commit_sha is None

    def test_pull_request_uses_head_sha(self):
        event = GitHubParser().parse(
            {"x-github-event": "pull_request"},
            {
                "action": "synchronize",
                "pull_request": {
                    "head": {"ref": "feature/x", "sha": SHA},
                    "base": {"ref": "main", "sha": "b" * 40},
                },
                "repository": {"id": 1},
                "sender": {},
            },
        )
        assert event.commit_sha == SHA

    def test_other_events_have_no_commit(self):
        event = GitHubParser().parse(
            {"x-github-event": "release"},
            {"release": {"tag_name": "v1"}, "repository": {"id": 1}, "sender": {}},
        )
        assert event.commit_sha is None


class GitLabCommitShaTests(SimpleTestCase):
    def test_gitlab_push_has_no_commit_yet(self):
        event = GitLabParser().parse(
            {},
            {"event_name": "push", "ref": "refs/heads/main", "after": SHA, "project_id": 7},
        )
        assert event.commit_sha is None
