# Standard Marketplace

The marketplace provides pre-built standard templates that you can install into your workspace with one click.

## Browsing

Go to **Marketplace** from the navigation bar. You'll see:

- **Packs** — curated bundles of related standards (e.g., "Repository Hygiene", "Security Essentials")
- **Individual standards** — browse all available standards with labels, author, and version info

## Installing

Click **Install** on any standard or **Install All** on a pack. This creates a copy in your workspace that you can customize freely. Installing doesn't attach it to any project yet: do that when you add a project, or from the project's **Standards** tab.

Installed standards show a green "Installed" badge in the marketplace.

## Customizing

After installing, the standard is yours to edit — change the code, adjust criteria, modify labels. The original marketplace standard is tracked as a source, so you can see when updates are available.

## Updates

When a marketplace standard is updated (new version), you'll see an "Update available" badge on your standard list and detail pages. Updating overwrites your code with the new version — a confirmation is shown before proceeding.

## Available packs

| Pack | Slug | For | Standards |
|------|------|-----|-----------|
| Repository Hygiene | `repo-hygiene` | Every repository | README Exists, License File, CODEOWNERS File, CI Configuration Required, GitGrit Badge in README |
| Documentation Standards | `documentation-standards` | Projects others contribute to or use | README Exists, Contributing Guide, Changelog Exists, License File |
| Git Hygiene | `git-hygiene` | Every repository | .gitignore Exists, No Large Binary Files |
| Security Essentials | `security-essentials` | Every repository | No Secrets in Code |
| Agentic Standards | `agentic-standards` | Repositories worked on with AI agents | Agent Instructions Present, Agent Instructions Not Stale, Agent Instructions Size Bounded, MCP Config Is Portable, Claude Settings — No Blanket Allow Rules |
| Node.js Standards | `nodejs-standards` | Node.js and TypeScript projects | Package.json Exists, NPM Scripts Defined, TypeScript Configured, Linter Configured, Dependency Lockfile Exists, Node.js Version Not EOL |
| Python Standards | `python-standards` | Python projects | Python Version Specified, Linter Configured, Dependency Lockfile Exists, Python Version Not EOL |
| Docker Standards | `docker-standards` | Containerized projects | Dockerfile Exists, .dockerignore Exists, No :latest Tag in Dockerfile |

Attach the language packs (Node.js, Python, Docker) only to projects in that language: on other projects their checks fail.

## From the terminal

```sh
gitgrit marketplace list                          # packs and standards, and what you installed
gitgrit marketplace view repo-hygiene             # a pack's standards
gitgrit marketplace install repo-hygiene          # a whole pack
gitgrit marketplace install --standard license-file
gitgrit marketplace update license-file           # to the latest version
```

Installed standards are enabled but attached to no project. Attach them with `gitgrit project attach`. See [Command Line](../getting-started/cli.md).
