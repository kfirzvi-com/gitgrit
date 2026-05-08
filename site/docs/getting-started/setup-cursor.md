# Connect Cursor to GitGrit

GitGrit's MCP server works with any MCP-aware editor. Cursor surfaces a
`.cursor/rules/gitgrit.mdc` rule file as a system prompt, which is how the
assistant learns to call `session_bootstrap` and `validate_edit` even when
your editor doesn't display the MCP server's `instructions` block.

## 1. Generate a generic-kind API token

In GitGrit, open **Profile → API Tokens & MCP** and click the
**Generic MCP client** tab. Name the token (e.g. *"Cursor at Acme"*) and
click **Create Generic Token**. Copy the value — it's shown only once.

## 2. Add the MCP server to Cursor

Open `~/.cursor/mcp.json` (create it if it doesn't exist) and merge in:

```json
{
  "mcpServers": {
    "GitGrit": {
      "type": "http",
      "url": "https://gitgrit.dev/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

Replace `YOUR_TOKEN` with the value from step 1. Reload Cursor — GitGrit
should appear under MCP servers.

## 3. Set up the rule file (one-time per project)

Open a chat in your project and type:

> set up GitGrit for this project

The assistant will call `export_setup_files(client="cursor")` and write
`.cursor/rules/gitgrit.mdc`. From here on, Cursor will inject this rule
file into every chat in this project so the assistant remembers to
bootstrap and call `validate_edit` before edits.

## 4. Bootstrap the project

Ask:

> what's the compliance status of this project?

The assistant calls `session_bootstrap` with the local git remote URL,
the server normalizes it (SSH ↔ HTTPS, `.git` strip, lowercased host),
and binds the local clone to a GitGrit project.

## 5. Edit normally

Before any file edit, the assistant calls `validate_edit` with the file's
prior and proposed content. The server reports only the violations this
edit *introduced*; pre-existing matches are reported as a count and never
block. Pre-existing violations stay your problem to deal with on your
schedule, not as a side-effect of a different change.

## Troubleshooting

- **The assistant doesn't call `validate_edit`.** Confirm
  `.cursor/rules/gitgrit.mdc` exists and has `alwaysApply: true` in its
  frontmatter. If it's missing, re-run *"set up GitGrit for this project"*.
- **`session_bootstrap` returns `error: no_match`.** The server compared
  your local git remote against your workspace's projects and found
  nothing close. Check that the project is added to the same workspace
  the token belongs to, then read the `candidates` field for near-misses.
- **`export_setup_files` returns `error: not_applicable`.** Your token is
  Claude-kind, not generic-kind. Generate a new generic-kind token from
  the **Generic MCP client** tab.
