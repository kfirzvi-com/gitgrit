# Adding Projects

Projects are repositories that GitGrit monitors. Each project belongs to a workspace and is connected to a platform (GitHub or GitLab).

## Prerequisites

Before adding a project, you need a **platform connection** configured in your workspace settings with a valid access token.

## Adding a project

1. Go to **Projects** → **Add Project**
2. Select the platform connection
3. Search for a repository by name
4. Click **Add** — GitGrit will:
    - Register a webhook on the repository
    - Fetch repository metadata (languages, topics, default branch)
    - Start evaluating policies on incoming events

## Webhook events

GitGrit listens for these events:

| Event | Description |
|-------|-------------|
| `push` | Code pushed to any branch |
| `pull_request` | PR opened, updated, or merged |
| `tag` | Tag created or deleted |

## Project details

Each project page shows:

- **Compliance score** — average of latest policy execution scores
- **Policies** — which policies apply, with manual run buttons
- **Recent activity** — webhook events and their results
- **Badge** — embeddable compliance badge for your README
- **Languages & tags** — fetched from the platform API
