"""Pull / merge request webhooks carry the source branch as the event ref (what
the run reads) and the target branch as target_ref (what the Branch/Tag Filter
matches). Both platforms map to the canonical ``pull_request`` event type."""
from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser


def test_github_push_ref():
    event = GitHubParser().parse(
        {"x-github-event": "push"},
        {"ref": "refs/heads/develop", "repository": {"id": 1}, "sender": {}},
    )
    assert event.event_type == "push"
    assert event.ref == "refs/heads/develop"
    assert event.target_ref is None


def test_github_pull_request_ref_is_head_and_target_is_base():
    event = GitHubParser().parse(
        {"x-github-event": "pull_request"},
        {
            "action": "opened",
            "pull_request": {"head": {"ref": "feature/x"}, "base": {"ref": "main"}},
            "repository": {"id": 1},
            "sender": {},
        },
    )
    assert event.event_type == "pull_request"
    assert event.ref == "feature/x"
    assert event.target_ref == "main"


def test_gitlab_push_keeps_event_name():
    event = GitLabParser().parse(
        {},
        {
            "event_name": "push",
            "object_kind": "push",
            "ref": "refs/heads/develop",
            "project_id": 7,
            "user_username": "bob",
        },
    )
    assert event.event_type == "push"
    assert event.ref == "refs/heads/develop"
    assert event.target_ref is None


def test_gitlab_merge_request_maps_to_pull_request_with_target():
    event = GitLabParser().parse(
        {},
        {
            "object_kind": "merge_request",
            "project": {"id": 7},
            "object_attributes": {"source_branch": "feature/y", "target_branch": "main"},
            "user": {"username": "bob"},
        },
    )
    assert event.event_type == "pull_request"
    assert event.ref == "feature/y"
    assert event.target_ref == "main"
