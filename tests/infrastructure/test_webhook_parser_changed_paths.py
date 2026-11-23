"""What a push changed, from its payload, so a monorepo push runs only the
projects whose directories it touched. A payload that can't list every change
says so (None) instead of listing some."""
from django.test import SimpleTestCase

from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser

COMMITS = [
    {"added": ["apps/web/a.ts"], "modified": ["README.md"], "removed": []},
    {"added": [], "modified": [], "removed": ["services/api/old.go"]},
]


def _github(**payload):
    base = {"repository": {"id": 1}, "ref": "refs/heads/main", "before": "b" * 40, "after": "a" * 40}
    return GitHubParser().parse({"x-github-event": "push"}, {**base, **payload})


def _gitlab(**payload):
    base = {"object_kind": "push", "project_id": 1, "ref": "refs/heads/main", "before": "b" * 40, "after": "a" * 40}
    return GitLabParser().parse({}, {**base, **payload})


class GitHubChangedPathsTests(SimpleTestCase):
    def test_a_push_lists_every_path_its_commits_touched(self):
        event = _github(commits=COMMITS)
        self.assertEqual(event.changed_paths, ("README.md", "apps/web/a.ts", "services/api/old.go"))
        self.assertEqual(event.base_sha, "b" * 40)

    def test_new_and_forced_pushes_are_unknown(self):
        self.assertIsNone(_github(commits=COMMITS, created=True).changed_paths)
        self.assertIsNone(_github(commits=COMMITS, forced=True).changed_paths)

    def test_a_pull_request_is_compared_from_its_base(self):
        event = GitHubParser().parse(
            {"x-github-event": "pull_request"},
            {"repository": {"id": 1}, "pull_request": {"base": {"ref": "main", "sha": "c" * 40}, "head": {"ref": "f", "sha": "d" * 40}}},
        )
        self.assertIsNone(event.changed_paths)
        self.assertEqual(event.base_sha, "c" * 40)


class GitLabChangedPathsTests(SimpleTestCase):
    def test_a_push_lists_every_path_its_commits_touched(self):
        event = _gitlab(commits=COMMITS, total_commits_count=2)
        self.assertEqual(event.changed_paths, ("README.md", "apps/web/a.ts", "services/api/old.go"))

    def test_more_commits_than_listed_is_unknown(self):
        self.assertIsNone(_gitlab(commits=COMMITS, total_commits_count=40).changed_paths)
