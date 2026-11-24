from __future__ import annotations

from datetime import datetime
from fnmatch import fnmatchcase

from app.domain.delivery import DeploymentEvent, DeploymentStrategy
from app.infrastructure.delivery.github_api import GitHubApi, github_time

# Tags without a release cost a commit lookup each; past this many, the rest
# are left out rather than slowing every refresh of a tag-heavy repository.
MAX_COMMIT_LOOKUPS = 100


class GitHubReleaseTags:
    """Each tag matching the release pattern (``v*`` by default) is a
    deployment. It happened when its GitHub release was published, or, for a
    tag with no release, when the tagged commit was committed. Drafts and
    pre-releases are not production."""

    strategy = DeploymentStrategy.RELEASE_TAGS

    def __init__(self, api: GitHubApi, pattern: str):
        self._api = api
        self._pattern = pattern or "*"

    def find(self, since: datetime) -> list[DeploymentEvent]:
        published, skipped = self._releases()
        events, lookups = [], 0
        for tag in self._api.pages("tags", {"per_page": 100}):
            name = tag["name"]
            if name in skipped or not fnmatchcase(name, self._pattern):
                continue
            sha = tag["commit"]["sha"]
            deployed_at = published.get(name)
            if deployed_at is None:
                if lookups == MAX_COMMIT_LOOKUPS:
                    continue
                lookups += 1
                deployed_at = self._committed_at(sha)
            if deployed_at >= since:
                events.append(
                    DeploymentEvent(
                        strategy=self.strategy, external_id=name, sha=sha, deployed_at=deployed_at, ref=name
                    )
                )
        return events

    def _releases(self) -> tuple[dict[str, datetime], set[str]]:
        published, skipped = {}, set()
        for release in self._api.pages("releases", {"per_page": 100}):
            if release["draft"] or release["prerelease"] or not release.get("published_at"):
                skipped.add(release["tag_name"])
            else:
                published[release["tag_name"]] = github_time(release["published_at"])
        return published, skipped

    def _committed_at(self, sha: str) -> datetime:
        return github_time(self._api.get(f"commits/{sha}")["commit"]["committer"]["date"])
