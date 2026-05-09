import difflib
import re

from app.domain.models import Project, Tenant
from app.infrastructure.sandbox.runner import SandboxRunner

RESOLVE_ERROR_NO_MATCH = "no_match"

_SSH_REMOTE_RE = re.compile(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$")
_HTTP_HOST_RE = re.compile(r"^(https?://)([^/]+)(.*)$")
_CREDENTIALS_RE = re.compile(r"(https?://)[^@/\s]+@")
_TRAILING_GIT_RE = re.compile(r"\.git/?$")


def _normalize_web_url(url: str | None) -> str | None:
    """Coerce a raw git remote URL into the credential-free HTTPS form Project.web_url uses."""
    if not url:
        return url
    url = url.strip()
    m = _SSH_REMOTE_RE.match(url)
    if m:
        url = f"https://{m.group(1)}/{m.group(2)}"
    url = _CREDENTIALS_RE.sub(r"\1", url)
    url = _TRAILING_GIT_RE.sub("", url)
    m = _HTTP_HOST_RE.match(url)
    if m:
        url = f"{m.group(1)}{m.group(2).lower()}{m.group(3)}"
    return url


def _normalize_full_path(path: str | None) -> str | None:
    if not path:
        return path
    path = path.strip().lstrip("/")
    return _TRAILING_GIT_RE.sub("", path)

_PROJECT_CONTEXT_API = """
# ProjectContext API Reference

When writing a GitGrit policy, your `evaluate(project)` function receives a `project` object
with the following methods:

## Methods

### `project.list_files() -> list[str]`
Returns a list of all file paths in the repository (recursive).

**Example:**
```python
files = project.list_files()
has_readme = any(f.lower().startswith("readme") for f in files)
```

### `project.get_file_content(path: str) -> str | None`
Returns the content of a file at the given path, or `None` if it doesn't exist.

**Example:**
```python
content = project.get_file_content(".github/CODEOWNERS")
if content is None:
    return {"passed": False, "score": 0, "message": "CODEOWNERS not found", "details": {}}
```

### `project.get_languages() -> dict[str, float]`
Returns a dict mapping language names to their percentage in the repo.

**Example:**
```python
{"Python": 85.3, "YAML": 14.7}
```

### `project.get_members() -> list[dict]`
Returns a list of dicts with `username` and `role` keys.

**Example:**
```python
[{"username": "alice", "role": "owner"}, {"username": "bob", "role": "developer"}]
```

### `project.get_contributors() -> list[dict]`
Returns a list of dicts with `username` and `commits` keys.

**Example:**
```python
[{"username": "alice", "commits": 42}, {"username": "bob", "commits": 7}]
```

### `project.get_default_branch() -> str`
Returns the name of the default branch (e.g. `"main"`, `"master"`).

### `project.get_topics() -> list[str]`
Returns a list of topic/tag strings applied to the repository.

### `project.get_metadata() -> dict`
Returns repository metadata with keys: `name`, `description`, `web_url`,
`created_at`, `updated_at`.

### `project.get_file_last_commit_date(path: str) -> str | None`
Returns the ISO 8601 timestamp of the most recent commit that touched
`path` on the default branch, or `None` if the file does not exist or
has no commit history. Useful for staleness / freshness checks on
specific tracked files.

**Example:**
```python
date_str = project.get_file_last_commit_date("CLAUDE.md")
# "2026-04-15T10:23:00Z" or None
```

## Return Format

Your `evaluate(project)` function must return a dict with exactly these keys:

```python
{
    "passed": bool,          # True if policy passes, False if it fails
    "score": int,            # 0-100 compliance score
    "message": str,          # Human-readable result summary
    "details": dict,         # Any additional details (can be empty dict)
}
```

## Complete Example

```python
def evaluate(project):
    content = project.get_file_content(".github/CODEOWNERS")
    if content is None:
        return {
            "passed": False,
            "score": 0,
            "message": "CODEOWNERS file not found",
            "details": {},
        }
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return {
            "passed": False,
            "score": 30,
            "message": "CODEOWNERS file exists but has no ownership rules",
            "details": {"line_count": 0},
        }
    return {
        "passed": True,
        "score": 100,
        "message": f"CODEOWNERS file found with {len(lines)} ownership rule(s)",
        "details": {"rule_count": len(lines)},
    }
```
""".strip()


class ProjectService:
    def list_projects(self, tenant: Tenant) -> list[dict]:
        return [
            self._serialize(p)
            for p in Project.objects.filter(tenant=tenant).order_by("name")
        ]

    def resolve_project(
        self,
        tenant: Tenant,
        repo_full_path: str | None = None,
        web_url: str | None = None,
    ) -> dict:
        """Map a local git remote to a GitGrit project.

        Returns the project dict (with ``matched_by``) on hit, or
        ``{"error": "no_match", "candidates": [...]}`` on miss — up to 5
        closest ``full_path`` matches to help the caller suggest alternatives.

        The Claude plugin pre-normalizes its remote URL client-side; the same
        normalization runs here so non-plugin MCP clients (Cursor, Cline, raw
        JSON-RPC) get the same hit rate when they pass raw output of
        ``git remote get-url origin``.
        """
        web_url = _normalize_web_url(web_url)
        repo_full_path = _normalize_full_path(repo_full_path)

        if repo_full_path:
            project = Project.objects.filter(
                tenant=tenant, full_path=repo_full_path
            ).first()
            if project:
                return {**self._serialize(project), "matched_by": "full_path"}

        if web_url:
            project = Project.objects.filter(tenant=tenant, web_url=web_url).first()
            if project:
                return {**self._serialize(project), "matched_by": "web_url"}

        all_paths = list(
            Project.objects.filter(tenant=tenant).values_list("full_path", flat=True)
        )
        candidates = difflib.get_close_matches(
            repo_full_path or "", all_paths, n=5, cutoff=0.4
        )
        return {"error": RESOLVE_ERROR_NO_MATCH, "candidates": candidates}

    def get_project_context_api(self) -> str:
        return _PROJECT_CONTEXT_API

    @staticmethod
    def _serialize(p: Project) -> dict:
        return {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "platform": p.platform,
            "full_path": p.full_path,
            "web_url": p.web_url,
            "default_branch": p.default_branch,
            "lifecycle": p.lifecycle,
            "languages": p.languages,
            "tags": p.tags,
        }


class SandboxService:
    def run_policy_test(self, policy_code: str, input_data: dict) -> dict:
        input_config = {
            "platform": "mock",
            "project_id": "test",
            "access_token": None,
            "mock_data": input_data,
        }
        runner = SandboxRunner()
        return runner.run(policy_code, input_config)
