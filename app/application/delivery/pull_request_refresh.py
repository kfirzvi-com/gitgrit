from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Iterable

from django.db.models import Max
from django.utils import timezone

from app.application.delivery.deployment_refresh import LOOKBACK
from app.application.delivery.repository_activity import RepositoryActivity
from app.domain.delivery import PullRequestFacts
from app.models import Project, PullRequest

# Read back a little before the newest change already stored, in case two
# changes shared a second or one landed while the last sync was reading.
OVERLAP = timedelta(minutes=5)


class PullRequestRefresh:
    """Brings a project's stored pull requests up to date.

    The first time, it reads every open pull request and every one changed
    within the metrics window. After that it reads only what changed since
    the newest change stored, which is usually one cheap request."""

    def __init__(self, now: Callable[[], datetime] = timezone.now):
        self._now = now

    def run(self, project: Project, activity: RepositoryActivity) -> int:
        newest = PullRequest.objects.filter(project=project).aggregate(newest=Max("updated_at"))["newest"]
        if newest is None:
            facts = [*activity.open_pull_requests(), *activity.pull_requests_updated_since(self._now() - LOOKBACK)]
        else:
            facts = activity.pull_requests_updated_since(newest - OVERLAP)
        return self.record(project, facts)

    @staticmethod
    def record(project: Project, facts: Iterable[PullRequestFacts]) -> int:
        """Store pull requests, replacing what was stored for the same
        numbers. Idempotent; a webhook's pull request is recorded this way
        too."""
        by_number = {fact.number: fact for fact in facts}
        PullRequest.objects.bulk_create(
            [
                PullRequest(
                    project=project,
                    number=fact.number,
                    title=fact.title[:500],
                    author=fact.author,
                    author_is_bot=fact.author_is_bot,
                    url=fact.url,
                    draft=fact.draft,
                    state=fact.state.value,
                    base_ref=fact.base_ref,
                    created_at=fact.created_at,
                    updated_at=fact.updated_at,
                    merged_at=fact.merged_at,
                    closed_at=fact.closed_at,
                )
                for fact in by_number.values()
            ],
            update_conflicts=True,
            unique_fields=["project", "number"],
            update_fields=[
                "title", "author", "author_is_bot", "url", "draft", "state", "base_ref",
                "created_at", "updated_at", "merged_at", "closed_at",
            ],
        )
        return len(by_number)
