# Artifact Projects

An artifact project is a project whose files are **build artifacts you upload**
instead of a Git repository: a built web app's `dist/`, a bundle, a release
package. Each upload is a **commit** of the project, and your standards check it
the way they check a pushed commit: same results, same branch health, same
history.

Use one when what you want to hold to your standards is the thing you ship
rather than its source, or when the files never live in a repository GitGrit can
reach (another team's builds, a vendor's deliverables, a platform that receives
uploads).

## How it maps to Git

| | Git project | Artifact project |
|---|---|---|
| A commit is | a commit on GitHub or GitLab | an uploaded archive |
| Its SHA | Git's SHA | the archive's content hash (40 hex characters) |
| Message, branch, author | from Git | given with the upload; the author is whoever uploaded |
| The event standards run on | `push`, `pull_request`, `tag` | `upload` |
| Standards read the files | through the Git platform's API | from the archive, unpacked read-only |

The same bytes uploaded again are the same commit: nothing new is stored, and the
standards run on it again.

## Create one

=== "Web"

    **Projects** → **Add Project** → **Artifact project**. Give it a name and,
    optionally, a stack (pick one or type a new name) and its first archive.

=== "CLI"

    ```sh
    gitgrit project add --artifact --name "Storefront" --stack "Web Team"
    ```

    Adding it again returns the same project. `--external-id` sets the id that
    makes it idempotent (the name by default).

=== "API"

    ```sh
    curl -X POST "https://app.gitgrit.dev/api/v1/workspaces/$WORKSPACE/projects/" \
      -H "Authorization: Bearer $GITGRIT_TOKEN" -H "Content-Type: application/json" \
      -d '{"type": "artifact", "name": "Storefront", "external_id": "storefront", "stack": "Web Team"}'
    ```

    `201` when created, `200` with the existing project when `external_id` is
    already taken. Without `standards`, the project gets every published
    standard whose events include `upload`.

## Upload a commit

=== "Web"

    On the project page, **Upload commit**: the archive, a commit message and a
    branch (the default branch when empty). The Results tab follows the run.

=== "CLI"

    ```sh
    gitgrit project upload dist.zip --project Storefront -m "Release 1.4.2" --wait
    ```

    `--wait` waits for the check and exits by the commit's score, the same way
    as [`gitgrit check`](cli.md) (`--fail-under 80` also fails a score under
    80), so a pipeline can gate on it.

=== "API"

    ```sh
    curl -X POST "https://app.gitgrit.dev/api/v1/workspaces/$WORKSPACE/projects/$PROJECT/commits/" \
      -H "Authorization: Bearer $GITGRIT_TOKEN" \
      -F archive=@dist.zip -F message="Release 1.4.2" -F branch=main
    ```

    The `202` response carries `commit.sha`. Poll
    `GET .../projects/$PROJECT/commits/<sha>/` until `running` is `0` for the
    results.

For automation, use a **workspace token** (workspace settings → API Tokens).

## What an archive may contain

An archive is a `.zip` or a `.tar.gz` (the API also takes plain, bzip2 and xz
tars). GitGrit checks it before
storing anything and rejects it, saying why, when:

- a path is absolute or climbs out with `..`,
- it holds links or devices (only files and folders count),
- it is larger than **50 MB**, unpacks to more than **200 MB**, or holds more
  than **20,000** files.

If every file sits in one top-level folder (`dist/`, `my-app-1.4/`), that folder
is dropped, so `index.html` is at the root either way.

## See a commit's files

In the **Results** tab, click a commit's SHA: its folder tree opens with sizes,
and clicking a file shows it. Text is shown as text (long minified lines wrap);
images get a preview. Nothing in an uploaded archive runs in your browser:
HTML and scripts are only ever shown as text.

## Writing standards for builds

Turn on the **`upload`** event in the standard's criteria; the Branch/Tag filter
matches the upload's branch. A standard sees the unpacked archive through the
usual [ProjectContext API](../api/project-context.md). `get_file_size` covers
files you cannot read as text, and an LLM standard's model reads large or
minified files page by page with `read_file_lines`. Repository facts (members,
contributors, commit dates) are empty for artifact projects.

```python
def evaluate(project):
    maps = [f for f in project.list_files() if f.endswith(".map")]
    if maps:
        return {"passed": False, "score": 0,
                "message": f"{len(maps)} source map(s) shipped", "details": {"files": maps}}
    return {"passed": True, "score": 100, "message": "No source maps shipped", "details": {}}
```

```python
BUDGET = 5 * 1024 * 1024

def evaluate(project):
    sizes = {f: project.get_file_size(f) or 0 for f in project.list_files()}
    too_big = {f: s for f, s in sizes.items() if s > BUDGET}
    if too_big:
        return {"passed": False, "score": 30,
                "message": f"{len(too_big)} file(s) over 5 MB", "details": {"files": too_big}}
    return {"passed": True, "score": 100, "message": "Every file is under 5 MB", "details": {}}
```

## Deleting

Deleting an artifact project (or its workspace) deletes its uploaded archives
too.
