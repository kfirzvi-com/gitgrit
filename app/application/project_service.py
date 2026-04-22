from app.domain.models import Project, Tenant
from app.infrastructure.sandbox.runner import SandboxRunner

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
            {
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
            for p in Project.objects.filter(tenant=tenant).order_by("name")
        ]

    def get_project_context_api(self) -> str:
        return _PROJECT_CONTEXT_API


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
