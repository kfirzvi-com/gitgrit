# Connect Cline to GitGrit

GitGrit's MCP server works with Cline (the open-source VS Code extension).
Cline surfaces a `.clinerules/gitgrit.md` file as a system prompt, which
is how the assistant learns to call `session_bootstrap` and
`validate_edit` even when your editor doesn't display the MCP server's
`instructions` block.

## 1. Generate a generic-kind API token

In GitGrit, open **Profile → API Tokens & MCP** and click the
**Generic MCP client** tab. Name the token (e.g. *"Cline at Acme"*) and
click **Create Generic Token**. Copy the value — it's shown only once.

## 2. Add the MCP server to Cline

Open Cline's MCP settings panel (the plug icon) and add a new server
with:

- **Name**: `GitGrit`
- **URL**: `https://gitgrit.dev/mcp/`
- **Authorization header**: `Bearer YOUR_TOKEN`

Replace `YOUR_TOKEN` with the value from step 1. Cline should now list
GitGrit's tools (`session_bootstrap`, `validate_edit`,
`export_setup_files`, …).

## 3. Set up the rule file (one-time per project)

Open a chat in your project and type:

> set up GitGrit for this project

The assistant will call `export_setup_files(client="cline")` and write
`.clinerules/gitgrit.md`. From here on, Cline will inject this rule file
into every chat in this project so the assistant remembers to bootstrap
and call `validate_edit` before edits.

## 4. Bootstrap the project

Ask:

> what's the compliance status of this project?

The assistant calls `session_bootstrap` with the local git remote URL,
the server normalizes it, and binds the local clone to a GitGrit project.

## 5. Edit normally

Before any file edit, the assistant calls `validate_edit` with the file's
prior and proposed content. The server reports only the violations this
edit *introduced*; pre-existing matches are reported as a count and never
block.

## Troubleshooting

- **The assistant doesn't call `validate_edit`.** Confirm
  `.clinerules/gitgrit.md` exists at the project root. If it's missing,
  re-run *"set up GitGrit for this project"*.
- **`session_bootstrap` returns `error: no_match`.** Check that the
  project is added to the same workspace the token belongs to. Read the
  `candidates` field in the response for near-misses.
- **`export_setup_files` returns `error: not_applicable`.** Your token is
  Claude-kind, not generic-kind. Generate a new generic-kind token from
  the **Generic MCP client** tab.
