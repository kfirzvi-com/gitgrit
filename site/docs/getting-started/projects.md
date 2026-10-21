# Adding Projects

A project is a repository GitGrit checks. Each project belongs to a workspace and comes in through one of the workspace's git platform connections.

## Connect a platform first

A workspace owner or admin connects GitHub or GitLab once, in **Workspace Settings** → **Git Platform Connections**:

- **GitHub App** (recommended for GitHub): click **Install GitHub App**, pick your organization and the repositories GitGrit may read. There's no token to rotate, and GitHub sends GitGrit every push through the App.
- **Access token** (GitLab, or GitHub without the App): pick the platform, paste a personal access token and click **Add Connection**. **How to generate a token?** lists the permissions it needs.

From the terminal: `gitgrit connection app` or `gitgrit connection add`. See [Command Line](cli.md).

## Add a repository

1. Go to **Projects** → **Add Project** and pick the connection. Right after connecting, you land here on your own.
2. Search for the repository and click **Select**.
3. Optionally set a **Lifecycle** and an **Owner**.
4. Under **Attach standards**, pick the standards to run and, if you like, their [importance](#importance). **None are attached by default.**
5. Click **Add Project**.

GitGrit then:

- reads the repository's languages and topics, so language-specific standards apply only where they fit,
- registers a webhook on the repository, for token connections (GitHub App connections already get every push through the App),
- runs the attached standards once on the default branch.

From the terminal, inside a clone:

```sh
gitgrit project add --all-standards
```

## Keeping results current

Standards run again on every push and pull request. To run them on demand, open the project's **Results** tab and click **Run on latest commit**, or run `gitgrit check`.

| Event | When |
|-------|------|
| `push` | Code pushed to any branch |
| `pull_request` | PR opened, updated, or merged |
| `tag` | Tag created or deleted |

A standard can limit which events and branches it runs on. See [Writing Standards](standards.md).

## The project page

- **Overview**: the project's [score](#the-score) and how many standards passed, failed or errored
- **Results**: each branch's score and its commits, each with its own score and every standard's message
- **Standards**: attach and detach standards and set their [importance](#importance)
- **Get your Badge**: an embeddable score badge for your README ([Compliance Badges](../features/badges.md))
- **Edit**: lifecycle and owner. **Remove** deletes the project, its results and its webhook.

## Importance

Each attached standard has an **importance**: how much it matters to this project.

| Importance | Meaning |
|---|---|
| **Required** 🛑 | if it fails, the project fails |
| **Major** (default) | counts fully toward this project's score |
| **Minor** | counts less toward this project's score |

Importance belongs to the attached standard, not to the standard itself, so the same standard can be Required on one project and Minor on another. Every attached standard starts at Major; detaching it and attaching it again starts over at Major.

Set it in the project's **Standards** tab: click a row's importance in the **Importance** column and pick one, or check several rows and use **Set importance**, then click **Save**. Required standards show a stop sign, and a line above the table counts them. **Any importance** filters the table to the attached standards of one importance.

The [API](https://app.gitgrit.dev/api/v1/docs/)'s list of a project's standards (`GET /api/v1/workspaces/{workspace_id}/projects/{project_id}/standards/`) returns each one's `importance`, and `PATCH /api/v1/workspaces/{workspace_id}/projects/{project_id}/standards/{standard_id}/` with `{"importance": "required"}` sets it.

Each run remembers the importance its standard had when it ran, so changing importance later never rescores an old commit; the next check uses the new one.

## The score

Every checked commit gets a **score** from 0 to 100, once **every expected standard has finished on it**. The expected standards are the attached, enabled standards that apply to the commit (its branch and the project's languages) when its check started. Until then the commit has no score: it is *checking*, or *incomplete* if a standard never finished (for example, only one standard was run by hand).

- A **Required** standard that fails, or could not be verified (its run errored, for any reason, GitGrit's own failures included), makes the score **0**. The project page says which.
- Otherwise the score is the **average of the standards' scores, weighted by importance**: Required and Major count 2, Minor counts 1. A Major or Minor standard that errored is left out.

The **project's score** is the score of the newest commit on the default branch that has one. Checking an old commit again never replaces a newer commit's score. A commit keeps its score while it is checked again, and the new check replaces it only once every expected standard has finished; if a newer commit is still checking or incomplete, the project page says so under the score.

Changing attachments or importance does not rescore anything: the next check does.

### Letters

GitGrit shows every score as a letter. The number underneath stays the same, and the API returns both.

| Letter | Score |
|---|---|
| **A+** | 100 |
| **A** | 90 or more |
| **B** | 75 or more |
| **C** | 60 or more |
| **D** | below 60 |
| **F** | a Required standard failed or could not be verified |

An **F** always means the project failed; a low average is a D.

In the API every score comes with a `display` object (`text`, `tone`, `spoken`): how GitGrit itself shows it. Show that instead of formatting the number yourself, and your screens read like GitGrit's. `/status/`'s `grade` is the same as its `display.text`.
