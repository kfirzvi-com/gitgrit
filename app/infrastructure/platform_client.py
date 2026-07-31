from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod

import requests

from app.domain.models import Platform, PlatformConnection

logger = logging.getLogger(__name__)


class PlatformClient(ABC):
    def __init__(self, connection: PlatformConnection):
        self.connection = connection
        self.base_url = connection.base_url.rstrip("/")
        self.token = connection.access_token

    @abstractmethod
    def search_projects(self, query: str = "") -> list[dict]:
        """Return list of {external_id, name, full_path, web_url, default_branch, description}."""

    @abstractmethod
    def create_webhook(self, external_id: str, target_url: str, secret: str) -> str:
        """Create webhook on repo, return webhook ID as string."""

    @abstractmethod
    def delete_webhook(self, external_id: str, webhook_id: str) -> None:
        """Delete webhook from repo."""

    @abstractmethod
    def test_token(self) -> bool:
        """Verify the token is valid."""

    def get_languages(self, external_id: str, full_path: str = "") -> list[str]:
        """Return list of language names for a project. Override per platform."""
        return []

    def get_topics(self, external_id: str, full_path: str = "") -> list[str]:
        """Return list of topic/tag names for a project. Override per platform."""
        return []

    def get_tree(self, full_path: str, ref: str = "") -> list[str]:
        """Return repo file paths (blobs only). Read-only. Override per platform."""
        return []

    def get_file_content(self, full_path: str, path: str, ref: str = "") -> str | None:
        """Return a file's decoded text, or None if missing/binary. Override per platform."""
        return None


class GitHubClient(PlatformClient):
    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def test_token(self) -> bool:
        resp = requests.get(f"{self.base_url}/user", headers=self._headers, timeout=10)
        return resp.status_code == 200

    def search_projects(self, query: str = "") -> list[dict]:
        results = []
        page = 1
        while True:
            resp = requests.get(
                f"{self.base_url}/user/repos",
                headers=self._headers,
                params={
                    "per_page": 100,
                    "sort": "updated",
                    "page": page,
                },
                timeout=15,
            )
            resp.raise_for_status()
            repos = resp.json()
            if not repos:
                break
            for repo in repos:
                if query and query.lower() not in repo["full_name"].lower():
                    continue
                results.append(
                    {
                        "external_id": str(repo["id"]),
                        "name": repo["name"],
                        "full_path": repo["full_name"],
                        "web_url": repo["html_url"],
                        "default_branch": repo.get("default_branch", "main"),
                        "description": repo.get("description") or "",
                    }
                )
            if len(repos) < 100:
                break
            page += 1
        return results

    def get_languages(self, external_id: str, full_path: str = "") -> list[str]:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/languages",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return list(resp.json().keys())

    def get_topics(self, external_id: str, full_path: str = "") -> list[str]:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/topics",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("names", [])

    def _default_branch(self, full_path: str) -> str:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")

    def get_tree(self, full_path: str, ref: str = "") -> list[str]:
        branch = ref or self._default_branch(full_path)
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/git/trees/{branch}",
            headers=self._headers,
            params={"recursive": "1"},
            timeout=20,
        )
        resp.raise_for_status()
        return [
            item["path"]
            for item in resp.json().get("tree", [])
            if item.get("type") == "blob"
        ]

    def get_file_content(self, full_path: str, path: str, ref: str = "") -> str | None:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/contents/{path}",
            headers=self._headers,
            params={"ref": ref} if ref else {},
            timeout=15,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        # Directories return a list; non-file types and binaries aren't usable.
        if isinstance(data, list) or data.get("type") != "file":
            return None
        if data.get("encoding") == "base64" and data.get("content"):
            try:
                return base64.b64decode(data["content"]).decode("utf-8", "replace")
            except Exception:
                return None
        return data.get("content") or None

    def create_webhook(self, external_id: str, target_url: str, secret: str) -> str:
        # Need full_name (owner/repo) — look up from external_id
        resp = requests.get(
            f"{self.base_url}/repositories/{external_id}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        full_name = resp.json()["full_name"]

        resp = requests.post(
            f"{self.base_url}/repos/{full_name}/hooks",
            headers=self._headers,
            json={
                "config": {
                    "url": target_url,
                    "content_type": "json",
                    "secret": secret,
                },
                "events": ["push", "pull_request", "create", "delete", "release"],
                "active": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return str(resp.json()["id"])

    def delete_webhook(self, external_id: str, webhook_id: str) -> None:
        resp = requests.get(
            f"{self.base_url}/repositories/{external_id}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        full_name = resp.json()["full_name"]

        requests.delete(
            f"{self.base_url}/repos/{full_name}/hooks/{webhook_id}",
            headers=self._headers,
            timeout=10,
        )


class GitLabClient(PlatformClient):
    @property
    def _headers(self):
        return {"PRIVATE-TOKEN": self.token}

    @property
    def _api_base(self):
        return f"{self.base_url}/api/v4"

    def test_token(self) -> bool:
        resp = requests.get(
            f"{self._api_base}/user", headers=self._headers, timeout=10
        )
        return resp.status_code == 200

    def search_projects(self, query: str = "") -> list[dict]:
        params = {
            "membership": "true",
            "per_page": 100,
            "order_by": "last_activity_at",
        }
        if query:
            params["search"] = query

        resp = requests.get(
            f"{self._api_base}/projects",
            headers=self._headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return [
            {
                "external_id": str(p["id"]),
                "name": p["name"],
                "full_path": p["path_with_namespace"],
                "web_url": p["web_url"],
                "default_branch": p.get("default_branch") or "main",
                "description": p.get("description") or "",
            }
            for p in resp.json()
        ]

    def get_languages(self, external_id: str, full_path: str = "") -> list[str]:
        resp = requests.get(
            f"{self._api_base}/projects/{external_id}/languages",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return list(resp.json().keys())

    def get_topics(self, external_id: str, full_path: str = "") -> list[str]:
        resp = requests.get(
            f"{self._api_base}/projects/{external_id}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("topics", [])

    def create_webhook(self, external_id: str, target_url: str, secret: str) -> str:
        resp = requests.post(
            f"{self._api_base}/projects/{external_id}/hooks",
            headers=self._headers,
            json={
                "url": target_url,
                "token": secret,
                "push_events": True,
                "merge_requests_events": True,
                "tag_push_events": True,
                "releases_events": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return str(resp.json()["id"])

    def delete_webhook(self, external_id: str, webhook_id: str) -> None:
        requests.delete(
            f"{self._api_base}/projects/{external_id}/hooks/{webhook_id}",
            headers=self._headers,
            timeout=10,
        )


def get_platform_client(connection: PlatformConnection) -> PlatformClient:
    if connection.platform == Platform.GITHUB:
        return GitHubClient(connection)
    elif connection.platform == Platform.GITLAB:
        return GitLabClient(connection)
    raise ValueError(f"Unknown platform: {connection.platform}")
