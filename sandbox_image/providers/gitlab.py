from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse

from providers.base import BaseProvider

_DEFAULT_BASE_URL = "https://gitlab.com"


class GitLabProvider(BaseProvider):
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
        self._project_cache: dict | None = None

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict | list:
        url = f"{self.base_url}/api/v4{path}"
        req = urllib.request.Request(url)
        req.add_header("PRIVATE-TOKEN", self.access_token)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if exc.fp else ""
            raise RuntimeError(
                f"GitLab API error {exc.code} for {url}: {body}"
            ) from exc

    def _get_raw(self, path: str) -> str | None:
        url = f"{self.base_url}/api/v4{path}"
        req = urllib.request.Request(url)
        req.add_header("PRIVATE-TOKEN", self.access_token)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            body = exc.read().decode() if exc.fp else ""
            raise RuntimeError(
                f"GitLab API error {exc.code} for {url}: {body}"
            ) from exc

    # ------------------------------------------------------------------
    # Cached project metadata (reused by multiple methods)
    # ------------------------------------------------------------------

    @property
    def _project(self) -> dict:
        if self._project_cache is None:
            encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
            self._project_cache = self._get(f"/projects/{encoded_id}")
        return self._project_cache

    # ------------------------------------------------------------------
    # BaseProvider implementation
    # ------------------------------------------------------------------

    def get_file_content(self, path: str) -> str | None:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        encoded_path = urllib.parse.quote(path, safe="")
        branch = self.get_default_branch()
        return self._get_raw(
            f"/projects/{encoded_id}/repository/files/{encoded_path}/raw?ref={branch}"
        )

    def list_files(self) -> list[str]:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        branch = self.get_default_branch()
        files = []
        page = 1
        while True:
            items = self._get(
                f"/projects/{encoded_id}/repository/tree"
                f"?ref={branch}&recursive=true&per_page=100&page={page}"
            )
            files.extend(
                item["path"] for item in items if item.get("type") == "blob"
            )
            if len(items) < 100:
                break
            page += 1
        return files

    def get_languages(self) -> dict[str, float]:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        return self._get(f"/projects/{encoded_id}/languages")

    def get_members(self) -> list[dict]:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        members = self._get(f"/projects/{encoded_id}/members/all?per_page=100")
        access_levels = {
            10: "guest",
            20: "reporter",
            30: "developer",
            40: "maintainer",
            50: "owner",
        }
        return [
            {
                "username": m["username"],
                "role": access_levels.get(m.get("access_level", 0), "unknown"),
            }
            for m in members
        ]

    def get_contributors(self) -> list[dict]:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        contributors = self._get(
            f"/projects/{encoded_id}/repository/contributors?per_page=100"
        )
        return [
            {
                "username": c.get("name", ""),
                "commits": c.get("commits", 0),
            }
            for c in contributors
        ]

    def get_default_branch(self) -> str:
        return self._project.get("default_branch", "main")

    def get_topics(self) -> list[str]:
        return self._project.get("topics", [])

    def get_file_last_commit_date(self, path: str) -> str | None:
        encoded_id = urllib.parse.quote(self.full_path or self.project_id, safe="")
        encoded_path = urllib.parse.quote(path, safe="/")
        branch = self.get_default_branch()
        try:
            commits = self._get(
                f"/projects/{encoded_id}/repository/commits"
                f"?path={encoded_path}&ref_name={branch}&per_page=1"
            )
        except RuntimeError:
            return None
        if not commits or not isinstance(commits, list):
            return None
        return commits[0].get("committed_date") or None

    def get_metadata(self) -> dict:
        p = self._project
        return {
            "name": p.get("name", ""),
            "description": p.get("description", "") or "",
            "web_url": p.get("web_url", ""),
            "created_at": p.get("created_at", ""),
            "updated_at": p.get("last_activity_at", ""),
        }
