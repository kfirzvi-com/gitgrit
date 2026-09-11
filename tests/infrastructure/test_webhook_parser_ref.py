"""Pull / merge request webhooks carry the source branch as the event ref, so
the Branch/Tag Filter gates them like pushes."""
from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser


def test_github_push_ref():
    event = GitHubParser().parse(
        {"x-github-event": "push"},
        {"ref": "refs/heads/develop", "repository": {"id": 1}, "sender": {}},
    )
    assert event.ref == "refs/heads/develop"


def test_github_pull_request_ref_is_head_branch():
    event = GitHubParser().parse(
        {"x-github-event": "pull_request"},
        {
            "action": "opened",
            "pull_request": {"head": {"ref": "feature/x"}, "base": {"ref": "main"}},
            "repository": {"id": 1},
            "sender": {},
        },
    )
    assert event.event_type == "merge_request"
    assert event.ref == "feature/x"


def test_gitlab_merge_request_ref_is_source_branch():
    event = GitLabParser().parse(
        {},
        {
            "object_kind": "merge_request",
            "project": {"id": 7},
            "object_attributes": {"source_branch": "feature/y", "target_branch": "main"},
            "user": {"username": "bob"},
        },
    )
    assert event.ref == "feature/y"
