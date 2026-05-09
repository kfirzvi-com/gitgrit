# Contributing to GitGrit

Thanks for taking the time to look at GitGrit. This document covers what you need to know to file a useful bug report, set up the project locally, and get a pull request merged.

## Ways to contribute

- **Bug reports.** Open a [GitHub issue](https://github.com/kfirzvi-com/gitgrit/issues/new) with reproduction steps, your environment (hosted vs self-hosted, Docker version, OS), and what you expected vs what you saw. If the bug touches the sandbox, include the policy code and the input data — without those it is very hard to reproduce.
- **Feature requests.** Open an issue describing the use case before writing code. We would rather discuss the shape early than ask you to refactor a finished PR.
- **New marketplace policies.** Policies live under `app/marketplace/` (seed data) and execute inside the sandbox. Each policy must ship with at least one passing and one failing test case. See the [policy guide](https://gitgrit.dev/getting-started/policies/) and [`ProjectContext` API](https://gitgrit.dev/api/project-context/).
- **Sandbox or platform capabilities.** Anything that changes the runner, the provider clients, or the MCP surface is a larger conversation — open an issue first so we can talk about isolation, scope, and migration impact before you build.
- **Documentation.** Docs live under `site/` (MkDocs). PRs that fix typos, clarify steps, or fill gaps are very welcome and do not need a prior issue.

## Reporting security vulnerabilities

**Do not** open a public issue for security bugs. See [`SECURITY.md`](SECURITY.md) for the private reporting process.

## Local development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.13+.

```bash
git clone https://github.com/kfirzvi-com/gitgrit.git
cd gitgrit

# Postgres
docker compose up -d

# Dependencies
uv sync

# Build the sandbox image (required before running policy execution or its tests)
uv run poe sandbox

# Database
uv run python manage.py migrate
uv run python manage.py seed_marketplace   # optional

# Dev server
uv run poe dev
```

Visit `http://localhost:8000`. The hosted-version setup guides at [gitgrit.dev/getting-started/](https://gitgrit.dev/getting-started/) apply locally too — the only difference is you point webhooks at your local tunnel.

## Running tests

```bash
uv run poe test               # full suite
uv run python manage.py test app.domain   # one app
uv run python manage.py test app.domain.tests.test_policy_extractor.TestPolicyExtractor.test_x   # one test
```

The suite uses `testcontainers` to spin up Postgres, so the Docker daemon must be running. Tests that exercise the sandbox runner (`tests/sandbox/`, `tests/plugin/e2e/`) require the `gitgrit-sandbox:latest` image — re-run `uv run poe sandbox` whenever you change anything under `sandbox_image/`.

If you add a new policy or sandbox capability, add tests that cover both the success path and at least one violation path. We do not merge new policy logic without test cases.

## Code style and commit conventions

- **Python style.** Match the surrounding code; no project-wide formatter is enforced today. Keep imports tidy and avoid speculative abstractions.
- **Layered architecture.** New code should respect the boundaries described in [`CLAUDE.md`](CLAUDE.md): `app/domain/` for business logic, `app/infrastructure/` for external integrations, `app/presentation/` for views. Domain code must not import from infrastructure.
- **Commit messages.** We use [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`. The subject explains the *why* in one line; details go in the body. Look at recent `git log` for examples.
- **One concern per PR.** Mixed PRs are hard to review and harder to revert. Split refactors out of feature work.

## Contributor License Agreement

GitGrit requires a signed CLA before we can merge your contribution. The agreement is short — read it at [`CLA.md`](CLA.md).

To sign, comment the following text exactly on your first pull request:

> I have read the CLA Document and I hereby sign the CLA

Our CLA bot records your signature in `.github/cla-signatures.json`; you only need to sign once. PRs from contributors without a signature will be blocked until the comment is posted.

## Pull request process

1. Fork the repository and create a topic branch off `main`. Use a descriptive name (`fix/sandbox-timeout`, `feat/gitlab-merge-request-comments`).
2. Make your changes. Add or update tests. Update relevant docs under `site/`.
3. Run the full test suite locally. PRs with failing CI will not be reviewed until they go green.
4. Open the PR against `main`. Fill in the description: what changed, why, and how you tested it. Link the issue it resolves.
5. Sign the CLA on the PR if this is your first contribution.
6. A maintainer will review. Expect at least one round of feedback — we are unhurried about review and prefer getting it right over merging fast.
7. Once approved and CI is green, a maintainer will merge. We use squash-merges so your individual commits do not need to be perfectly clean, but the PR title should be a good Conventional Commit summary.

## Questions

If you are unsure whether something is in scope or how to approach it, open a [discussion](https://github.com/kfirzvi-com/gitgrit/discussions) or a draft PR with a question in the description. Asking early is always cheaper than rewriting later.
