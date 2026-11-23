---
title: "ProjectContext API"
---

# ProjectContext API

The `project` object passed to every standard's `evaluate` function provides these methods.

Paths are relative to the **project's root**: the repository root, or, for a
project inside a [monorepo](../getting-started/monorepos.md), its directory
(`package.json` there means `apps/web/package.json`). The two
`*_repository_*` methods reach the whole repository on purpose.

## Methods

### `project.get_file_content(path) -> str | None`

Read the content of a file by its path. Returns `None` if the file doesn't exist.

```python
content = project.get_file_content("README.md")
if content and "## Contributing" in content:
    # Has a contributing section
```

### `project.get_file_size(path) -> int | None`

Size of a file in bytes, including files you cannot read as text (images,
audio, wasm). Known for [artifact projects](../getting-started/artifact-projects.md);
`None` on Git repositories.

```python
too_big = [f for f in project.list_files() if (project.get_file_size(f) or 0) > 5_000_000]
```

### `project.read_file_lines(path, start=1, count=100) -> dict | None`

Part of a file as numbered lines, for reading large or minified files a page at
a time. Lines longer than 200 characters (a minified bundle is often one line)
are first broken after `;`, `,`, braces or parentheses. Each call returns about
5,000 characters at most and says where to continue (`next_start`, `None` at
the end). This is how an LLM standard's model reads big files;
`get_file_content` stays the raw file.

```python
page = project.read_file_lines("assets/app.js")
# {"path": "assets/app.js", "total_lines": 2140,
#  "lines": ["1: (function(){\"use strict\";", ...], "next_start": 61}
```

### `project.list_files() -> list[str]`

List all file paths in the project (the whole repository, or the project's
directory inside a monorepo), relative to the project's root.

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

### `project.get_file_last_commit_date(path: str) -> str | None`

ISO 8601 timestamp of the most recent commit that touched `path` on the
default branch. Returns `None` if the file does not exist or has no
commit history. Useful for staleness / freshness checks on specific
tracked files.

```python
date_str = project.get_file_last_commit_date("CLAUDE.md")
# "2026-04-15T10:23:00Z"
```

### `project.get_repository_file_content(path) -> str | None`

Read a file anywhere in the repository, by its path from the repository root,
also outside the project's own directory. For a project inside a monorepo,
this reaches what lives at the root: a workspace lockfile, CI config,
`CODEOWNERS`. Same as `get_file_content` for a whole-repository project.

```python
lock = project.get_file_content("pnpm-lock.yaml") or project.get_repository_file_content("pnpm-lock.yaml")
```

### `project.list_repository_files() -> list[str]`

Every file path in the whole repository, from the repository root. Same as
`list_files` for a whole-repository project.

## Execution environment

- Standards run in **isolated gVisor containers** with no network access
- Execution timeout: **30 seconds**
- Memory limit: **128 MB**
- Only the `project` API is available — no filesystem, no imports beyond the standard library
- For an [artifact project](../getting-started/artifact-projects.md), `project` reads the
  uploaded commit's files; members, contributors, topics and commit dates are empty
