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

Each time the standards run on a commit (a push, a pull request, **Run**) is one **check** of it, and a commit reads its **newest check, alone**: a standard the newest check did not run is "not run", even if an earlier check ran it. A check reports nothing until **every expected standard has a result in it**: it passed or it failed. The expected standards are the attached, enabled standards that apply to the commit (its branch and the project's languages) when the check started. Each check, and so each commit, has one **outcome**, decided in this order:

1. **Checking**: a standard is still running on it.
2. **No score**: an expected standard **errored** (its run produced no result, for any reason, GitGrit's own failures and a run stuck for over an hour included) or **never ran** in that check (for example, only one standard was run by hand). This holds for every importance, Required too, and even when a Required standard failed. The project page says which standard errored or was not run; run them all on the commit again.
3. **Failed**: every standard ran and a **Required** standard failed. Failed is a verdict, not a number: the commit has no score, reads **F**, and the project page says which standard failed it.
4. **Scored**: every standard ran and no Required standard failed. The score is the **average of the standards' scores, weighted by importance**: Required and Major count 2, Minor counts 1. Every standard can fail and the score still be a number, even 0: that is a low score, not a failed project.

Whether a standard **passed or failed** is the standard's own decision; its score is its partial credit. A standard can fail with a high score, and only its score counts toward the average.

A **branch** reads its **newest commit**, whatever its outcome, and the **project's score** is its default branch's. Checking an old commit again never replaces a newer commit's. While the newest commit is being checked the project has no grade yet; when it has **no score**, neither does the project, and GitGrit says why wherever it shows the project: the Overview and Results tabs (which standard errored or was not run, and a button to run the commit again), the project's card, the dashboard's and stacks' counts (as no data, with the reason on hover), the map's hover, the API's `commit_score` and `gitgrit health`.

On the **Results** tab, open a commit to see every check of it on a timeline: a circle per check with its score inside, newest on the left and selected, since the commit reads it. Hover a circle for when and how it ran; step through them with the arrows, or pick one, to see what that check found.

Changing attachments or importance does not rescore anything: the next check does.

### Letters

GitGrit shows a commit's score, and so a branch's and a project's, as a letter. The number underneath stays the same, and the API returns both. Each standard's own result on a commit stays a number from 0 to 100.

| Letter | Score | Health |
|---|---|---|
| **A+** | 100 | Healthy |
| **A** | 90 or more | Healthy |
| **B** | 75 or more | Needs attention |
| **C** | 60 or more | Needs attention |
| **D** | below 60 (in orange) | Needs attention |
| **F** | every standard ran and a Required one failed | Failed |
| **—** | no score: a standard errored or never ran | No data |

An **F** always means the project failed; a low average is a D.

### Health

Everywhere GitGrit colours a project, a stack or a score, it means one of four things, from one rule: **healthy** (90 or more), **needs attention** (below 90), **failed** (a Required standard failed, in red; nothing else is red), and **no data**. A project has one health; many projects together never do: a stack and the dashboard show how many of their projects are failed, need attention, are healthy or have no data.

"Needs attention" on the dashboard and in the notifications pane lists only what stops a project from having a good score: **Required standards that failed** (each fails its project; listed first, in red), then **runs that errored**, of any importance (the commit has no score until they run). A Major or Minor standard that failed only lowers the score, so it is not listed.

In the API a commit score is one object: `outcome` (`checking`, `no_score`, `failed` or `scored`: read it first), `value` (the score, only when scored; `null` otherwise), `reason` (why it failed, "X failing", or has no score, "X errored", "Y not run") and `display` (`text`, `tone`, `spoken`): how GitGrit itself shows it. Show `display` instead of formatting the number yourself, and your screens read like GitGrit's; `display.tone` is the health: `healthy`, `needs_attention`, `failed` or `unknown`. `/status/`'s `grade` is the same as its `display.text`.
