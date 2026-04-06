# ProjectContext API

The `project` object passed to every policy's `evaluate` function provides these methods:

## Methods

### `project.get_file_content(path) -> str | None`

Read the content of a file by its path. Returns `None` if the file doesn't exist.

```python
content = project.get_file_content("README.md")
if content and "## Contributing" in content:
    # Has a contributing section
```

### `project.list_files() -> list[str]`

List all file paths in the repository.

```python
files = project.list_files()
has_ci = any(f.startswith(".github/workflows/") for f in files)
```

### `project.get_languages() -> dict[str, float]`

Language breakdown as percentages.

```python
languages = project.get_languages()
# {"Python": 72.5, "Dockerfile": 15.0, "YAML": 12.5}
```

### `project.get_members() -> list[dict]`

Project members with roles.

```python
members = project.get_members()
# [{"username": "alice", "role": "maintainer"}, ...]
```

### `project.get_contributors() -> list[dict]`

Contributors with commit counts.

```python
contributors = project.get_contributors()
# [{"username": "alice", "commits": 142}, ...]
```

### `project.get_default_branch() -> str`

Name of the default branch.

```python
branch = project.get_default_branch()  # "main"
```

### `project.get_topics() -> list[str]`

Repository topics/tags.

```python
topics = project.get_topics()
# ["python", "backend", "api"]
```

### `project.get_metadata() -> dict`

General repository metadata.

```python
meta = project.get_metadata()
# {
#   "name": "my-project",
#   "description": "A cool project",
#   "web_url": "https://github.com/org/my-project",
#   "created_at": "2024-01-01T00:00:00Z",
#   "updated_at": "2024-06-01T00:00:00Z",
# }
```

## Execution environment

- Policies run in **isolated gVisor containers** with no network access
- Execution timeout: **30 seconds**
- Memory limit: **128 MB**
- Only the `project` API is available — no filesystem, no imports beyond the standard library
