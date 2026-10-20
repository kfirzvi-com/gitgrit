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
4. Under **Attach standards**, pick the standards to run. **None are attached by default.**
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

- **Overview**: the grade, one letter from A+ to F with its reason, from each attached standard's latest result on its home branch (see [Grades](../features/grades.md)), and how many standards passed, failed or errored
- **Results**: results per branch and commit, with each standard's message
- **Standards**: attach and detach standards, and mark which ones are Critical
- **Get your Badge**: an embeddable grade badge for your README ([Compliance Badges](../features/badges.md))
- **Edit**: lifecycle and owner. **Remove** deletes the project, its results and its webhook.
