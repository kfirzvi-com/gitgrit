# Writing Policies

Policies are Python functions that evaluate a repository and return a compliance result.

## Structure

Every policy must define an `evaluate` function that receives a `project` object:

```python
def evaluate(project):
    files = project.list_files()

    if "README.md" in files:
        return {
            "passed": True,
            "score": 100,
            "message": "README found",
            "details": {},
        }

    return {
        "passed": False,
        "score": 0,
        "message": "No README found",
        "details": {},
    }
```

## Return value

The `evaluate` function must return a dictionary with:

| Key | Type | Description |
|-----|------|-------------|
| `passed` | `bool` | Whether the policy passed |
| `score` | `int` | Score from 0 to 100 |
| `message` | `str` | Human-readable result summary |
| `details` | `dict` | Additional data (shown in execution details) |

## Available API

The `project` object provides methods to query the repository. See the full [ProjectContext API](../api/project-context.md) reference.

## Criteria filters

Policies can be filtered to run only on specific events, branches, or languages:

- **Events** — `push`, `pull_request`, `tag`
- **Branch filter** — regex pattern matched against the event ref (e.g., `^refs/heads/main$`)
- **Languages** — only run if the project uses specific languages

Leaving a filter empty means "match all."

## Test cases

Each policy can have test cases that validate the logic with mock data. Test cases define:

- **Input** — mock data for `ProjectContext` methods (e.g., `list_files`, `get_file_content`)
- **Expected** — expected `passed` and `score` values

Run tests from the policy editor to verify your logic before deploying.
