# GitGrit

**Define your engineering standards as code — and see how every repository measures up.**

[![CI](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml/badge.svg)](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-gitgrit.dev-informational)](https://gitgrit.dev)

GitGrit is a developer-experience platform that gives engineering leaders visibility into how their teams build, and gives developers actionable guidance to improve. Define organization-wide standards as version-controlled Python policies, and GitGrit evaluates every repository against them automatically on each push, pull request, and tag — rolling the results into a per-project score and a live badge.

A hosted version runs at **[app.gitgrit.dev](https://app.gitgrit.dev)**, and the full documentation lives at **[gitgrit.dev](https://gitgrit.dev)**. This repository is the source for the platform, the policy sandbox, the marketplace content, the MCP server, and the Claude Code authoring plugin.

---

## What it does

- **Standards as code, not checklists.** Express your standards as Python policies with full access to repo files, languages, members, branch protection, and history — no DSL to learn.
- **Automatic evaluation.** Webhooks run matching policies on every push, pull request, and tag, across GitHub and GitLab in one workspace.
- **Visible scores.** Each project gets a score and an embeddable [badge](https://gitgrit.dev/features/badges/) so teams can see where they stand and where to improve.
- **Marketplace.** Install curated [policy packs](https://gitgrit.dev/features/marketplace/) in one click, then customize.
- **AI-native authoring.** A Claude Code plugin and an MCP server help LLMs draft, test, and refactor policies — with every policy running in an isolated sandbox.

The full feature tour is on the [docs home](https://gitgrit.dev).

## Quick start

Sign in at [app.gitgrit.dev](https://app.gitgrit.dev), connect a GitHub or GitLab instance, add a project, then install or write a policy. The full 5-minute walkthrough is in the [Quickstart guide](https://gitgrit.dev/getting-started/quickstart/).

## Writing a policy

A policy is a Python `evaluate(project)` function that returns a result dict:

```python
def evaluate(project):
    if "README.md" not in project.list_files():
        return {"passed": False, "score": 0, "message": "No README", "details": {}}
    return {"passed": True, "score": 100, "message": "README looks good", "details": {}}
```

Policies receive a typed `ProjectContext`, run sandboxed, and ship with mock-data test cases. See the [policy guide](https://gitgrit.dev/getting-started/policies/) and the [`ProjectContext` API reference](https://gitgrit.dev/api/project-context/).

## Claude Code plugin & MCP server

The [`plugin/`](plugin/) directory is a Claude Code plugin that makes your editing session aware of the workspace's active policies and adds `/gitgrit-status`, `/gitgrit-refresh`, and `/gitgrit-check`. GitGrit also ships an MCP server that exposes project context and policy data to LLM clients ([Cursor](https://gitgrit.dev/getting-started/setup-cursor/), [Cline](https://gitgrit.dev/getting-started/setup-cline/), [generic MCP clients](https://gitgrit.dev/getting-started/setup-generic/)).

> Policies drafted or edited by an LLM must be reviewed by a human and run against their test cases before you trust them in production.

## Self-hosting

GitGrit is open source under MIT and runs anywhere, including airgapped environments. Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.13+.

```bash
git clone https://github.com/kfirzvi-com/gitgrit.git
cd gitgrit
docker compose up -d      # Postgres
uv sync
uv run poe sandbox        # build the policy sandbox image
uv run poe migrate
uv run poe seed           # optional — marketplace packs
uv run poe dev            # http://localhost:8000
```

Full instructions and production deployment notes are in the [self-hosting docs](https://gitgrit.dev/self-hosting/).

## Documentation

Everything lives at **[gitgrit.dev](https://gitgrit.dev)** (source under [`site/`](site/)):

- [Quickstart](https://gitgrit.dev/getting-started/quickstart/) · [Adding projects](https://gitgrit.dev/getting-started/projects/) · [Writing policies](https://gitgrit.dev/getting-started/policies/) · [`ProjectContext` API](https://gitgrit.dev/api/project-context/)
- [Marketplace](https://gitgrit.dev/features/marketplace/) · [Badges](https://gitgrit.dev/features/badges/) · [Versioning](https://gitgrit.dev/features/versioning/) · [Analytics](https://gitgrit.dev/features/analytics/) · [Self-hosting](https://gitgrit.dev/self-hosting/)

## Contributing

Contributions are welcome — read [`CONTRIBUTING.md`](CONTRIBUTING.md), sign the [CLA](CLA.md), and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Good starter tasks are labeled [`good first issue`](https://github.com/kfirzvi-com/gitgrit/labels/good%20first%20issue).

## Security

Found a vulnerability? Please don't open a public issue — see [`SECURITY.md`](SECURITY.md) for the private reporting process.

## License

MIT — see [`LICENSE`](LICENSE).
