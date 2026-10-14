# GitGrit

**Define your engineering standards as code — and see how every repository measures up.**

[![CI](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml/badge.svg)](https://github.com/kfirzvi-com/gitgrit/actions/workflows/ci.yml)
[![GitGrit compliance](https://app.gitgrit.dev/badge/8b2d60f9-69dd-46cc-a56b-621c13dace9a.svg)](https://app.gitgrit.dev/projects/8b2d60f9-69dd-46cc-a56b-621c13dace9a/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-gitgrit.dev-informational)](https://gitgrit.dev)

GitGrit is a developer-experience platform that gives engineering leaders visibility into how their teams build, and gives developers actionable guidance to improve. Define organization-wide standards as version-controlled Python code, and GitGrit evaluates every repository against them automatically on each push, pull request, and tag — rolling the results into a per-project score and a live badge.

A hosted version runs at **[app.gitgrit.dev](https://app.gitgrit.dev)**, and the full documentation lives at **[gitgrit.dev](https://gitgrit.dev)**. This repository is the source for the platform, the standard sandbox, the marketplace content, and the public API.

---

## What it does

- **Standards as code, not checklists.** Express your standards as Python code with full access to repo files, languages, members, branch protection, and history — no DSL to learn.
- **Automatic evaluation.** Webhooks run matching standards on every push, pull request, and tag, across GitHub and GitLab in one workspace.
- **Visible scores.** Each project gets a score and an embeddable [badge](https://gitgrit.dev/features/badges/) so teams can see where they stand and where to improve.
- **Marketplace.** Install curated [standard packs](https://gitgrit.dev/features/marketplace/) in one click, then customize.
- **Public API.** A REST API (OpenAPI at `/api/v1/schema/`) for scripts, CI/CD and AI agents — projects, health, commit checks and standards, with every standard running in an isolated sandbox.

The full feature tour is on the [docs home](https://gitgrit.dev).

## Quick start

Request access at [app.gitgrit.dev](https://app.gitgrit.dev); once approved, connect a GitHub or GitLab instance, add a project, then install or write a standard. The full 5-minute walkthrough is in the [Quickstart guide](https://gitgrit.dev/getting-started/quickstart/).

## Writing a standard

A standard is a Python `evaluate(project)` function that returns a result dict:

```python
def evaluate(project):
    if "README.md" not in project.list_files():
        return {"passed": False, "score": 0, "message": "No README", "details": {}}
    return {"passed": True, "score": 100, "message": "README looks good", "details": {}}
```

Standards receive a typed `ProjectContext`, run sandboxed, and ship with mock-data test cases. See the [standard guide](https://gitgrit.dev/getting-started/standards/) and the [`ProjectContext` API reference](https://gitgrit.dev/api/project-context/).

## Public API

`/api/v1/` exposes projects, health per branch, commit checks and standards — the same data as the web app. Authenticate with OAuth (`gitgrit auth login` in the upcoming CLI), a personal token from your profile page, or a workspace token from the workspace settings (for CI/CD). Interactive docs live at `/api/v1/docs/`.

> Standards drafted or edited by an LLM must be reviewed by a human and run against their test cases before you trust them in production.

## Self-hosting

GitGrit is open source under MIT and runs anywhere, including airgapped environments. Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.13+.

```bash
git clone https://github.com/kfirzvi-com/gitgrit.git
cd gitgrit
docker compose up -d      # Postgres
uv sync
uv run poe sandbox        # build the standard sandbox image
uv run poe migrate
uv run poe seed           # optional — marketplace packs
uv run poe dev            # http://localhost:8000
```

Full instructions and production deployment notes are in the [self-hosting docs](https://gitgrit.dev/self-hosting/).

## Documentation

Everything lives at **[gitgrit.dev](https://gitgrit.dev)** (source under [`site/`](site/)):

- [Quickstart](https://gitgrit.dev/getting-started/quickstart/) · [Adding projects](https://gitgrit.dev/getting-started/projects/) · [Writing standards](https://gitgrit.dev/getting-started/standards/) · [`ProjectContext` API](https://gitgrit.dev/api/project-context/)
- [Marketplace](https://gitgrit.dev/features/marketplace/) · [Badges](https://gitgrit.dev/features/badges/) · [Versioning](https://gitgrit.dev/features/versioning/) · [Analytics](https://gitgrit.dev/features/analytics/) · [Self-hosting](https://gitgrit.dev/self-hosting/)

## Contributing

Contributions are welcome — read [`CONTRIBUTING.md`](CONTRIBUTING.md), sign the [CLA](CLA.md), and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Good starter tasks are labeled [`good first issue`](https://github.com/kfirzvi-com/gitgrit/labels/good%20first%20issue).

## Security

Found a vulnerability? Please don't open a public issue — see [`SECURITY.md`](SECURITY.md) for the private reporting process.

## License

MIT — see [`LICENSE`](LICENSE).
