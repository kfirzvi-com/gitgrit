from __future__ import annotations

from datetime import datetime
from typing import Callable

from django.utils import timezone

from app.application.delivery.deployment_refresh import LOOKBACK
from app.application.delivery.repository_activity import RepositoryActivity
from app.models import DeliverySettings, Deployment, Project, ShippedCommit

# Deployments whose commits one sync reads at most; the rest wait for the
# next sync, so a first sync of a busy project stays short.
PER_SYNC = 30


class ShipmentRefresh:
    """Reads which commits each new successful deployment brought to
    production: those between the previous successful deployment's commit
    and its own. A commit deployed again (a redeploy, a second region)
    brings nothing new. Each deployment is read once; what the platform can
    no longer compare (a commit gone) counts as nothing shipped."""

    def __init__(self, now: Callable[[], datetime] = timezone.now):
        self._now = now

    def run(self, project: Project, settings: DeliverySettings, activity: RepositoryActivity) -> int:
        strategy = settings.strategy_in_use
        if strategy is None:
            return 0
        shipped = Deployment.objects.filter(project=project, strategy=strategy, succeeded=True)
        unread = shipped.filter(changes_synced_at__isnull=True, deployed_at__gte=self._now() - LOOKBACK)
        read = 0
        for deployment in unread.order_by("deployed_at")[:PER_SYNC]:
            earlier = shipped.filter(deployed_at__lt=deployment.deployed_at).order_by("-deployed_at")
            commits = []
            if not earlier.filter(sha=deployment.sha).exists():
                previous = earlier.first()
                if previous is not None:
                    commits = activity.commits_between(previous.sha, deployment.sha) or []
            ShippedCommit.objects.bulk_create(
                [
                    ShippedCommit(
                        deployment=deployment,
                        sha=commit.sha,
                        authored_at=commit.authored_at,
                        first_parent_sha=commit.first_parent_sha,
                    )
                    for commit in commits
                ],
                ignore_conflicts=True,
            )
            deployment.changes_synced_at = self._now()
            deployment.save(update_fields=["changes_synced_at"])
            read += 1
        return read
