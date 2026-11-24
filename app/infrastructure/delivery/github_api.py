from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable, Iterator

import requests
from django.core.cache import caches

from app.application.delivery import RateLimited, SourceUnavailable
from app.domain.delivery import RateLimit

TIMEOUT = 15
MAX_PAGES = 20
# Cached answers outlive several syncs; one that ages out costs a single
# full request the next time.
CACHE_SECONDS = 7 * 24 * 3600
# Part of every cache key: raise it whenever what a ``slim`` keeps changes,
# or an unchanged answer (304) would hand back an old, trimmed-down body.
CACHE_VERSION = 2

Slim = Callable[[dict], dict]


class GitHubApi:
    """Read-only calls to one repository's GitHub REST API, for delivery
    syncs. A refusal becomes ``SourceUnavailable`` naming the token
    permission that is missing.

    Every answer is kept with its ETag and asked for again conditionally:
    GitHub answers an unchanged resource with ``304 Not Modified``, which
    does not count against the rate limit, so a quiet repository costs
    almost nothing to sync. The allowance left is remembered per token, and
    once it runs low (``RateLimit.is_low``) calls stop with ``RateLimited``
    until it resets.
    """

    def __init__(self, base_url: str, token: str, full_path: str, cache=None, now=None):
        self._repo_url = f"{base_url.rstrip('/')}/repos/{full_path}"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._token_key = hashlib.sha256(token.encode()).hexdigest()[:32]
        self._cache = cache if cache is not None else caches["platform"]
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get(self, path: str, params: dict | None = None, permission: str = "Contents", slim: Slim | None = None):
        body, _ = self._fetch(f"{self._repo_url}/{path}", params, permission, slim)
        return body

    def pages(
        self,
        path: str,
        params: dict | None = None,
        permission: str = "Contents",
        key: str = "",
        slim: Slim | None = None,
    ) -> Iterator[dict]:
        """Every item of a paginated list, following GitHub's ``next`` links.
        ``key`` names the list inside an object response (``workflow_runs``);
        ``slim`` trims each item to what the caller reads before it is cached."""
        trim = _list_slimmer(key, slim) if slim else None
        url, query = f"{self._repo_url}/{path}", params
        for _ in range(MAX_PAGES):
            body, next_url = self._fetch(url, query, permission, trim)
            yield from (body.get(key, []) if key else body)
            url, query = next_url, None
            if not url:
                return

    def _fetch(self, url: str, params: dict | None, permission: str, slim: Slim | None) -> tuple:
        self._check_allowance()
        key = self._cache_key(url, params)
        cached = self._cache.get(key)
        headers = dict(self._headers)
        if cached:
            headers["If-None-Match"] = cached["etag"]
        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        self._note_allowance(response)
        if response.status_code == 304 and cached:
            return cached["body"], cached["next"]
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            raise RateLimited(_reset_time(response))
        if response.status_code == 403:
            raise SourceUnavailable(
                f"The GitHub token can't read this repository's {permission.lower()}: give it "
                f"{permission} read access, with this repository among those it can reach."
            )
        response.raise_for_status()
        body = response.json()
        if slim:
            body = slim(body)
        next_url = response.links.get("next", {}).get("url")
        if etag := response.headers.get("ETag"):
            self._cache.set(key, {"etag": etag, "body": body, "next": next_url}, CACHE_SECONDS)
        return body, next_url

    def _cache_key(self, url: str, params: dict | None) -> str:
        query = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        # Per token: two workspaces' tokens may see the same URL differently.
        return f"gh-etag:v{CACHE_VERSION}:" + hashlib.sha256(f"{self._token_key} {url}?{query}".encode()).hexdigest()

    def _allowance_key(self) -> str:
        return f"gh-allowance:{self._token_key}"

    def _check_allowance(self) -> None:
        allowance = self._cache.get(self._allowance_key())
        if allowance and allowance.is_low(self._now()):
            raise RateLimited(allowance.resets_at)

    def _note_allowance(self, response: requests.Response) -> None:
        limit, remaining = response.headers.get("X-RateLimit-Limit"), response.headers.get("X-RateLimit-Remaining")
        if limit is None or remaining is None:
            return
        allowance = RateLimit(limit=int(limit), remaining=int(remaining), resets_at=_reset_time(response))
        self._cache.set(self._allowance_key(), allowance, 3600)


def _reset_time(response: requests.Response) -> datetime:
    reset = response.headers.get("X-RateLimit-Reset")
    return datetime.fromtimestamp(int(reset), tz=timezone.utc) if reset else datetime.now(timezone.utc)


def _list_slimmer(key: str, slim: Slim) -> Slim:
    """Keeps only the list, each item slimmed: the rest of an object
    response (a compare's files) is not read, so not kept."""

    def trim(body):
        if key:
            return {key: [slim(item) for item in body.get(key, [])]}
        return [slim(item) for item in body]

    return trim


def github_time(value: str) -> datetime:
    """A GitHub timestamp (``2026-11-16T20:44:47Z``) as an aware datetime."""
    return datetime.fromisoformat(value)
