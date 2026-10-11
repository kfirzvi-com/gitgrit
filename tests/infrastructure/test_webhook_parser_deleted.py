"""A push that deletes its branch is marked as such, on both platforms."""
from django.test import SimpleTestCase

from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import DELETED_SHA, GitLabParser


class GitHubDeletedPushTests(SimpleTestCase):
    def _push(self, **payload):
        return GitHubParser().parse(
            {"x-github-event": "push"},
            {"ref": "refs/heads/feature/x", "repository": {"id": 1}, "sender": {}, **payload},
        )

    def test_a_branch_deletion_is_marked_deleted(self):
        self.assertTrue(self._push(deleted=True, after="0" * 40).deleted)

    def test_an_ordinary_push_is_not(self):
        self.assertFalse(self._push(deleted=False).deleted)
        self.assertFalse(self._push().deleted)


class GitLabDeletedPushTests(SimpleTestCase):
    def _push(self, after):
        return GitLabParser().parse(
            {},
            {"object_kind": "push", "ref": "refs/heads/feature/x", "project_id": 7, "after": after},
        )

    def test_a_branch_deletion_is_marked_deleted(self):
        self.assertTrue(self._push(DELETED_SHA).deleted)

    def test_an_ordinary_push_is_not(self):
        self.assertFalse(self._push("a" * 40).deleted)
