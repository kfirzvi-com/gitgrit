from __future__ import annotations

import json
import urllib.request
import urllib.error

from providers.base import BaseProvider

_DEFAULT_BASE_URL = "https://api.github.com"


class GitHubProvider(BaseProvider):
    def __init__(
        self,
        project_id: str,
        access_token: str,
        base_url: str = "",
        full_path: str = "",
    ) -> None:
        self.project_id = project_id
        self.access_token = access_token
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.full_path = full_path
        self._repo_cache: dict | None = None

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict | list:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self.access_token}")
        req.add_header("Accept", "application/vnd.github+json")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if exc.fp else ""
            raise RuntimeError(
                f"GitHub API error {exc.code} for {url}: {body}"
            ) from exc

    # ------------------------------------------------------------------
    # Cached repo metadata (reused by multiple methods)
    # ------------------------------------------------------------------

    @property
    def _repo(self) -> dict:
        if self._repo_cache is None:
            self._repo_cache = self._get(f"/repos/{self.full_path}")
        return self._repo_cache

    # ------------------------------------------------------------------
    # BaseProvider implementation
    # ------------------------------------------------------------------

    def list_files(self) -> list[str]:
        branch = self.get_default_branch()
        tree = self._get(
            f"/repos/{self.full_path}/git/trees/{branch}?recursive=1"
        )
        return [
            entry["path"]
            for entry in tree.get("tree", [])
            if entry.get("type") == "blob"
        ]

    def get_languages(self) -> dict[str, float]:
        raw: dict = self._get(f"/repos/{self.full_path}/languages")
        total = sum(raw.values()) or 1
        return {lang: round(bytes_count / total * 100, 1) for lang, bytes_count in raw.items()}

    def get_members(self) -> list[dict]:
        collaborators: list = self._get(f"/repos/{self.full_path}/collaborators")
        return [
            {
                "username": c["login"],
                "role": c.get("role_name", "contributor"),
            }
            for c in collaborators
        ]

    def get_contributors(self) -> list[dict]:
        contributors: list = self._get(f"/repos/{self.full_path}/contributors")
        return [
            {
                "username": c["login"],
                "commits": c.get("contributions", 0),
            }
            for c in contributors
        ]

    def get_default_branch(self) -> str:
        return self._repo["default_branch"]

    def get_topics(self) -> list[str]:
        return self._repo.get("topics", [])

    def get_metadata(self) -> dict:
        r = self._repo
        return {
            "name": r.get("name", ""),
            "description": r.get("description", "") or "",
            "web_url": r.get("html_url", ""),
            "created_at": r.get("created_at", ""),
            "updated_at": r.get("updated_at", ""),
        }
