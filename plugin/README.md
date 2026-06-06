# GitGrit Claude Code Plugin

A Claude Code plugin that makes your editing session aware of GitGrit's active compliance policies. It:

- Auto-detects the current git repo at session start and resolves it to a GitGrit project via MCP.
- Loads the project's active policies into the session.
- Reminds Claude to run the enforcement check before every Edit or Write.
- Provides `/gitgrit-status`, `/gitgrit-refresh`, `/gitgrit-check` slash commands.

## Install (local dev)

This directory is both a Claude Code plugin and a single-plugin marketplace. Register the marketplace, then install the plugin from it:

```bash
/plugin marketplace add /absolute/path/to/gitgrit/plugin
/plugin install gitgrit@gitgrit
```

When prompted, supply:
- `api_token` — a workspace API token from `gitgrit.dev/settings/tokens`.
- `api_url` — leave blank for `https://gitgrit.dev/mcp/`, or set to your self-hosted MCP URL.

Restart the session after install so the `SessionStart` hook fires.

## Install (published)

Once this directory is mirrored to `kfirzvi-com/gitgrit-plugin`:

```bash
/plugin marketplace add kfirzvi-com/gitgrit-plugin
/plugin install gitgrit@gitgrit
```

## How it works

1. **SessionStart hook** (`scripts/session-init.sh`) runs `git remote get-url origin`, strips any embedded credentials, derives the `owner/repo` full-path, and emits an `additionalContext` block telling Claude to call `session_bootstrap` (one round-trip returning project, status, and active policies) and then write the session state file.

2. **PreToolUse hook** (`scripts/enforce-check.sh`) runs before every Edit or Write. If the session state file exists, it re-raises a short reminder that enforcement is active. If the file is absent (project not resolved), it exits silently.

3. The **enforcement rule itself lives on the server**, in the `Policy Enforcement` section of the MCP server instructions. The plugin never re-states the rule — both hooks and the `policy-enforcement` skill are pointers to that single source of truth. Each policy returned by `session_bootstrap` carries a structured `rules` block (watched files, kind-tagged forbidden patterns, and local-enforceability / completeness flags) extracted server-side, so the plugin does not parse Python at edit time.

## Session state file

`{project_id, project_name, policies_loaded}` for the current repo is kept at `$XDG_CACHE_HOME/gitgrit/<hash>.json` (falls back to `~/.cache/gitgrit/<hash>.json`). The filename is a 16-char prefix of the SHA-256 of the absolute `.git` directory path, so two clones of the same repo on disk each get their own state. Nothing is written inside the working tree — Claude Code blocks writes to `.git/`, and we don't want to pollute the repo root with an untracked file for every user.

## Scope limits

- Matches `Edit` and `Write` only. `MultiEdit` and `NotebookEdit` are not hooked in v1 — add them to `hooks/hooks.json` if you need notebook or bulk-edit coverage.
- Local enforcement is **advisory**. The authoritative verdict is the server sandbox's execution of `evaluate(project)`. When they disagree, the sandbox wins.
- Policies that call `get_members`, `get_contributors`, or inspect git history cannot be enforced locally and are skipped during editing.

## Publishing

This plugin lives inside the main GitGrit server repo at `plugin/` so server-side enforcement changes and plugin hook-output changes stay in sync in a single PR. When you're ready to publish:

```bash
# Mirror plugin/ as the root of a separate public repo:
git subtree push --prefix=plugin origin gitgrit-plugin-main
```

Or add a release workflow that mirrors `plugin/` on tag.
