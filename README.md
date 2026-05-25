# GitGrit

**Policy-as-code compliance and best-practice enforcement for GitHub and GitLab.**

[![CI](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml/badge.svg)](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-gitgrit.dev-informational)](https://gitgrit.dev)

GitGrit lets platform and DevOps teams define organization-wide standards as version-controlled Python policies, then evaluates every repository against them on push, pull request, and tag events. Policies run in gVisor-sandboxed containers, results roll up into a per-project compliance score, and a live SVG badge advertises that score back in the repo's README.

A hosted version runs at **[app.gitgrit.dev](https://app.gitgrit.dev)**. This repository is the source for the platform, the policy sandbox, the marketplace seed content, the MCP server, and the Claude Code authoring plugin.

---

## Why GitGrit

- **One source of truth for "good repo" standards.** Stop relying on per-team checklists, pinned Slack messages, or pre-commit hooks that only some people install.
- **Policies are Python, not YAML.** Real expressiveness — query files, languages, members, branch protection, recent commits — without learning a DSL.
- **Sandboxed by default.** Untrusted policy code runs inside gVisor-isolated Docker containers. Authors can iterate without operators worrying about RCE on the worker.
- **GitHub and GitLab in the same UI.** One workspace, multiple connections, mixed projects.
- **Visible compliance.** Per-project score, embeddable badge, marketplace of curated policies for common standards.
- **AI-native authoring.** A Claude Code plugin and an MCP server let LLMs help draft, test, and refactor policies — with a sandboxed runner enforcing safe execution.

## Features

- **Policy-as-code** — Python `evaluate(project)` functions with a typed `ProjectContext` API ([reference](https://gitgrit.dev/api/project-context/)).
- **Webhook-driven evaluation** — push, pull-request, and tag events on GitHub and GitLab automatically run matching policies.
- **gVisor-sandboxed execution** — every policy runs in an isolated container with no network and a strict filesystem.
- **Test cases** — each policy ships with mock-data test cases that validate logic before deployment.
- **Marketplace + packs** — install curated policies one-click. Initial packs: *Repository Hygiene*, *Security Essentials*.
- **Compliance badges** — public SVG badge per project, color-coded by score.
- **Workspace multi-tenancy** — members, connections, projects, stacks, and policies scoped per workspace.
- **MCP server** — exposes project context, policy state, and execution history to LLM clients.
- **Claude Code plugin** — under [`plugin/`](plugin/), turns Claude Code into a policy-aware editor.
- **OAuth sign-in** — Google, GitHub, and GitLab via `django-allauth`.

## Architecture at a glance

```
            ┌───────────────────────────┐
GitHub ──▶  │  Webhook receiver         │
GitLab ──▶  │  (Django + DRF)           │
            └────────────┬──────────────┘
                         │ enqueue
                         ▼
            ┌───────────────────────────┐
            │  Policy runner            │
            │  (gVisor + Docker)        │
            └────────────┬──────────────┘
                         │ result
                         ▼
            ┌───────────────────────────┐
            │  PostgreSQL               │
            │  scores, runs, audit log  │
            └────────────┬──────────────┘
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
   Web UI           Badge SVG          MCP server
 (HTMX +         (gitgrit.dev/         (LLM clients,
  DaisyUI)        badge/<id>.svg)       Claude Code)
```

## Quick start

### Use the hosted service

1. Sign in at [app.gitgrit.dev](https://app.gitgrit.dev) — a workspace is created automatically.
2. Connect a platform: **Workspace Settings → New Connection → GitHub or GitLab** (paste a personal access token).
3. Add a project: **Projects → Add Project**, pick the repo. GitGrit registers a webhook for you.
4. Install a policy from the **Marketplace**, or write your own under **Policies → New Policy**.
5. Push to the repo. Results show up on the project page and in the badge.

Full walkthrough: [Quickstart guide](https://gitgrit.dev/getting-started/quickstart/).

### Self-host

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.13+.

```bash
git clone https://github.com/kfirzvi-com/gitgrit.git
cd gitgrit

# Postgres
docker compose up -d

# Dependencies
uv sync

# Build the sandbox image (required for policy execution)
uv run poe sandbox

# DB
uv run python manage.py migrate
uv run python manage.py seed_marketplace   # optional — loads marketplace packs

# Dev server
uv run poe dev
```

Visit `http://localhost:8000` and sign in.

For production deployment we use [Kamal 2](https://kamal-deploy.org). See `config/deploy.yml` and the deployment notes in [`CLAUDE.md`](CLAUDE.md).

## Writing your first policy

```python
def evaluate(project):
    files = project.list_files()

    if "README.md" not in files:
        return {"passed": False, "score": 0, "message": "No README", "details": {}}

    content = project.get_file_content("README.md") or ""
    if len(content) < 200:
        return {"passed": False, "score": 50, "message": "README is too short", "details": {"length": len(content)}}

    return {"passed": True, "score": 100, "message": "README looks good", "details": {}}
```

Policies receive a `ProjectContext` and return a result dict (`passed`, `score`, `message`, `details`). See the [policy guide](https://gitgrit.dev/getting-started/policies/) and the [`ProjectContext` API reference](https://gitgrit.dev/api/project-context/).

## Claude Code plugin

The [`plugin/`](plugin/) directory is both a Claude Code plugin and a single-plugin marketplace. It makes your editing session aware of the workspace's active policies, reminds Claude to check before edits, and exposes `/gitgrit-status`, `/gitgrit-refresh`, and `/gitgrit-check`.

```bash
# Inside Claude Code
/plugin marketplace add /absolute/path/to/gitgrit/plugin
/plugin install gitgrit@gitgrit
```

When prompted, supply an API token from `app.gitgrit.dev/settings/tokens`.

> **Note on AI-generated rules.** Policies generated or edited by an LLM must be reviewed by a human and run against test cases before being trusted in production. Diffs from untrusted PRs can reach LLM-exposed tools — treat anything they suggest as untrusted input.

## MCP server

GitGrit ships an MCP server that exposes project context and policy data to LLM clients (Claude Code, Cline, Cursor, generic MCP-aware tools). Setup guides:

- [Cursor](https://gitgrit.dev/getting-started/setup-cursor/)
- [Cline](https://gitgrit.dev/getting-started/setup-cline/)
- [Generic MCP client](https://gitgrit.dev/getting-started/setup-generic/)

The server is read-only by default; write capabilities require explicit token scopes.

## Documentation

The full docs site is at **[gitgrit.dev](https://gitgrit.dev)**. Source lives under [`site/`](site/) (MkDocs).

- [Quickstart](https://gitgrit.dev/getting-started/quickstart/)
- [Adding projects](https://gitgrit.dev/getting-started/projects/)
- [Writing policies](https://gitgrit.dev/getting-started/policies/)
- [`ProjectContext` API](https://gitgrit.dev/api/project-context/)
- [Marketplace](https://gitgrit.dev/features/marketplace/)
- [Badges](https://gitgrit.dev/features/badges/)
- [Versioning](https://gitgrit.dev/features/versioning/)
- [Analytics](https://gitgrit.dev/features/analytics/)

## Project layout

```
gitgrit/
├── app/                  # Main Django app
│   ├── domain/           # Business logic and services
│   ├── infrastructure/   # Sandbox runner, GitHub/GitLab clients, MCP
│   ├── presentation/     # Views, URLs, HTMX endpoints
│   └── templates/        # HTML templates (HTMX + DaisyUI)
├── gitgrit/              # Django settings package
├── sandbox_image/        # Dockerfile for the gVisor-sandboxed policy runner
├── plugin/               # Claude Code plugin (also a marketplace)
├── site/                 # MkDocs source for gitgrit.dev
├── config/               # Kamal deployment config
└── tests/                # Pytest suite
```

## Contributing

Contributions are welcome. Before opening a pull request:

1. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev-environment setup, test commands, and review process.
2. Sign the [Contributor License Agreement](CLA.md) — our CLA bot will prompt you on your first PR.
3. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

Looking for a starter task? Check issues labeled [`good first issue`](https://github.com/kfirzvi-com/gitgrit/labels/good%20first%20issue).

## Security

Found a vulnerability? **Please do not open a public issue.** See [`SECURITY.md`](SECURITY.md) for our private reporting process and the threat model (sandbox isolation, webhook signature verification, OAuth token storage, MCP prompt-injection considerations).

## License

GitGrit is licensed under the [MIT License](LICENSE).
