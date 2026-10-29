from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from urllib.parse import quote

import requests

from app.domain.models import AuthMethod, Platform, PlatformConnection, ArtifactCommit

logger = logging.getLogger(__name__)


class PlatformClient(ABC):
    def __init__(self, connection: PlatformConnection):
        self.connection = connection
        self.base_url = connection.base_url.rstrip("/")
        # Route through the auth-method seam: PAT connections return the stored
        # token; GitHub App connections mint a short-lived installation token.
        self.token = connection.get_access_token()

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

    def list_branches(self, external_id: str, full_path: str) -> list[str]:
        """Every branch name in the repository. Override per platform."""
        return []

    def list_commits(
        self, external_id: str, full_path: str, branch: str, page: int = 1, per_page: int = 20
    ) -> list[dict]:
        """One page of a branch's commits, newest first, each as
        ``{sha, message, author, date, url}`` (date is an ISO 8601 string).
        Override per platform."""
        return []

    def head_commit(self, external_id: str, full_path: str, branch: str) -> dict:
        """A branch's latest commit as ``{sha, date}`` (date is ISO 8601).
        Override per platform."""
        return {}


class GitHubClient(PlatformClient):
    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def _is_app(self) -> bool:
        return self.connection.auth_method == AuthMethod.GITHUB_APP

    def test_token(self) -> bool:
        if self._is_app:
            # `/user` is a user-scoped endpoint: an installation token gets 403
            # "Resource not accessible by integration" there, which would report
            # a perfectly healthy App connection as an invalid token. Probe the
            # endpoint the token is actually for instead.
            resp = requests.get(
                f"{self.base_url}/installation/repositories",
                headers=self._headers,
                params={"per_page": 1},
                timeout=10,
            )
            return resp.status_code == 200
        resp = requests.get(f"{self.base_url}/user", headers=self._headers, timeout=10)
        return resp.status_code == 200

    def search_projects(self, query: str = "") -> list[dict]:
        results = []
        page = 1
        while True:
            if self._is_app:
                # GitHub App installation tokens list only the repos the App is
                # installed on, via a dedicated endpoint that wraps the list in
                # a {"repositories": [...]} envelope (no "sort" param).
                resp = requests.get(
                    f"{self.base_url}/installation/repositories",
                    headers=self._headers,
                    params={"per_page": 100, "page": page},
                    timeout=15,
                )
                resp.raise_for_status()
                repos = resp.json().get("repositories", [])
            else:
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

    def list_branches(self, external_id: str, full_path: str) -> list[str]:
        names: list[str] = []
        for page in range(1, 11):
            resp = requests.get(
                f"{self.base_url}/repos/{full_path}/branches",
                headers=self._headers,
                params={"per_page": 100, "page": page},
                timeout=10,
            )
            resp.raise_for_status()
            batch = resp.json()
            names += [b["name"] for b in batch]
            if len(batch) < 100:
                break
        return names

    def list_commits(
        self, external_id: str, full_path: str, branch: str, page: int = 1, per_page: int = 20
    ) -> list[dict]:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/commits",
            headers=self._headers,
            params={"sha": branch, "page": page, "per_page": per_page},
            timeout=10,
        )
        resp.raise_for_status()
        commits = []
        for c in resp.json():
            info = c.get("commit") or {}
            author = info.get("author") or {}
            commits.append(
                {
                    "sha": c["sha"],
                    "message": info.get("message", ""),
                    "author": author.get("name") or (c.get("author") or {}).get("login", ""),
                    "date": author.get("date", ""),
                    "url": c.get("html_url", ""),
                }
            )
        return commits

    def head_commit(self, external_id: str, full_path: str, branch: str) -> dict:
        resp = requests.get(
            f"{self.base_url}/repos/{full_path}/commits/{quote(branch, safe='')}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        author = (data.get("commit") or {}).get("author") or {}
        return {"sha": data.get("sha", ""), "date": author.get("date", "")}

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

    def list_branches(self, external_id: str, full_path: str) -> list[str]:
        names: list[str] = []
        for page in range(1, 11):
            resp = requests.get(
                f"{self._api_base}/projects/{external_id}/repository/branches",
                headers=self._headers,
                params={"per_page": 100, "page": page},
                timeout=10,
            )
            resp.raise_for_status()
            batch = resp.json()
            names += [b["name"] for b in batch]
            if len(batch) < 100:
                break
        return names

    def list_commits(
        self, external_id: str, full_path: str, branch: str, page: int = 1, per_page: int = 20
    ) -> list[dict]:
        resp = requests.get(
            f"{self._api_base}/projects/{external_id}/repository/commits",
            headers=self._headers,
            params={"ref_name": branch, "page": page, "per_page": per_page},
            timeout=10,
        )
        resp.raise_for_status()
        return [
            {
                "sha": c["id"],
                "message": c.get("message", ""),
                "author": c.get("author_name", ""),
                "date": c.get("committed_date") or c.get("created_at", ""),
                "url": c.get("web_url", ""),
            }
            for c in resp.json()
        ]

    def head_commit(self, external_id: str, full_path: str, branch: str) -> dict:
        resp = requests.get(
            f"{self._api_base}/projects/{external_id}/repository/branches/{quote(branch, safe='')}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        commit = resp.json().get("commit") or {}
        return {"sha": commit.get("id", ""), "date": commit.get("committed_date", "")}

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


class ArtifactClient(PlatformClient):
    """The artifact connection's "platform": GitGrit itself. An artifact
    project's commits are its uploads (see ``ArtifactCommit``), each on a
    branch, so the project page's history reads them
    through the same interface as a Git platform's."""

    def search_projects(self, query: str = "") -> list[dict]:
        return []

    def create_webhook(self, external_id: str, target_url: str, secret: str) -> str:
        raise ValueError("Artifact projects receive no webhooks.")

    def delete_webhook(self, external_id: str, webhook_id: str) -> None:
        pass

    def test_token(self) -> bool:
        return True

    def _commits(self, external_id: str):
        return ArtifactCommit.objects.filter(
            project__platform_connection=self.connection,
            project__external_id=external_id,
        ).order_by("-created_at")

    def list_branches(self, external_id: str, full_path: str) -> list[str]:
        return sorted(set(self._commits(external_id).values_list("branch", flat=True)))

    def list_commits(
        self, external_id: str, full_path: str, branch: str, page: int = 1, per_page: int = 20
    ) -> list[dict]:
        start = (page - 1) * per_page
        commits = self._commits(external_id).filter(branch=branch)[start : start + per_page]
        return [
            {
                "sha": c.sha,
                "message": c.message or f"Upload of {c.file_count} files",
                "author": c.author,
                "date": c.created_at.isoformat(),
                "url": "",
            }
            for c in commits
        ]

    def head_commit(self, external_id: str, full_path: str, branch: str) -> dict:
        commit = self._commits(external_id).filter(branch=branch).first()
        return {"sha": commit.sha, "date": commit.created_at.isoformat()} if commit else {}


def get_platform_client(connection: PlatformConnection) -> PlatformClient:
    if connection.platform == Platform.GITHUB:
        return GitHubClient(connection)
    elif connection.platform == Platform.GITLAB:
        return GitLabClient(connection)
    elif connection.platform == Platform.ARTIFACT:
        return ArtifactClient(connection)
    raise ValueError(f"Unknown platform: {connection.platform}")
