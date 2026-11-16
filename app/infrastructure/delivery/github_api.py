from __future__ import annotations

from datetime import datetime
from typing import Iterator

import requests

from app.application.delivery import SourceUnavailable

TIMEOUT = 15
MAX_PAGES = 20


class GitHubApi:
    """Read-only calls to one repository's GitHub REST API, for the
    deployment sources. A refusal becomes ``SourceUnavailable`` naming the
    token permission that is missing."""

    def __init__(self, base_url: str, token: str, full_path: str):
        self._repo_url = f"{base_url.rstrip('/')}/repos/{full_path}"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str, params: dict | None = None, permission: str = "Contents"):
        return self._request(f"{self._repo_url}/{path}", params, permission).json()

    def pages(
        self, path: str, params: dict | None = None, permission: str = "Contents", key: str = ""
    ) -> Iterator[dict]:
        """Every item of a paginated list, following GitHub's ``next`` links.
        ``key`` names the list inside an object response (``workflow_runs``)."""
        url, query = f"{self._repo_url}/{path}", params
        for _ in range(MAX_PAGES):
            response = self._request(url, query, permission)
            body = response.json()
            yield from (body.get(key, []) if key else body)
            url, query = response.links.get("next", {}).get("url"), None
            if not url:
                return

    def _request(self, url: str, params: dict | None, permission: str) -> requests.Response:
        response = requests.get(url, headers=self._headers, params=params, timeout=TIMEOUT)
        if response.status_code == 403:
            raise SourceUnavailable(
                f"The GitHub token can't read {permission.lower()}: give it "
                f"{permission} read access."
            )
        response.raise_for_status()
        return response


def github_time(value: str) -> datetime:
    """A GitHub timestamp (``2026-11-16T20:44:47Z``) as an aware datetime."""
    return datetime.fromisoformat(value)
