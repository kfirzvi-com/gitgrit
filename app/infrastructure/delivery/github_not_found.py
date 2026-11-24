from __future__ import annotations

from app.application.delivery import SourceUnavailable


class GitHubNotFound(SourceUnavailable):
    """GitHub has no such thing (404) or cannot compare it (422): a commit
    gone after a force-push, a workflow file renamed, a repository moved.
    Adapters that expect it catch it; anywhere else it is noted on the
    project like any source that cannot be read."""
