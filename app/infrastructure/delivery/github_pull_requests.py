from __future__ import annotations

from app.domain.delivery import PullRequestFacts
from app.infrastructure.delivery.github_api import github_time

# The fields kept from GitHub's pull request objects (API items and webhook
# payloads have the same shape); the rest is too much to cache.
_KEPT = ("number", "title", "html_url", "draft", "created_at", "updated_at", "merged_at", "closed_at")


def slim_pull_request(item: dict) -> dict:
    user = item.get("user") or {}
    return {
        **{key: item.get(key) for key in _KEPT},
        "user": {"login": user.get("login", ""), "type": user.get("type", "")},
        "base": {"ref": (item.get("base") or {}).get("ref", "")},
    }


def pull_request_facts(item: dict) -> PullRequestFacts:
    """A GitHub pull request object as facts."""
    user = item.get("user") or {}

    def moment(key):
        return github_time(item[key]) if item.get(key) else None

    return PullRequestFacts(
        number=item["number"],
        title=item.get("title") or "",
        author=user.get("login", ""),
        author_is_bot=user.get("type") == "Bot",
        url=item.get("html_url") or "",
        draft=bool(item.get("draft")),
        created_at=moment("created_at"),
        updated_at=moment("updated_at"),
        merged_at=moment("merged_at"),
        closed_at=moment("closed_at"),
        base_ref=(item.get("base") or {}).get("ref", ""),
    )


def pull_request_from_payload(payload: dict) -> PullRequestFacts | None:
    """The pull request a GitHub ``pull_request`` webhook is about, or None
    when the payload carries none (another platform's event)."""
    item = payload.get("pull_request")
    if not isinstance(item, dict) or "number" not in item or not item.get("created_at"):
        return None
    return pull_request_facts(item)
