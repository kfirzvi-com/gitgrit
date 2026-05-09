# Connect a generic MCP client to GitGrit

For MCP-aware clients without a rules-directory convention — MCP
Inspector, raw JSON-RPC, GPT-driven IDEs, custom integrations — GitGrit
relies on the MCP `initialize` response to deliver operating
instructions. If your client surfaces those instructions to the model,
no rule file is needed.

## 1. Generate a generic-kind API token

In GitGrit, open **Profile → API Tokens & MCP** and click the
**Generic MCP client** tab. Name the token and click
**Create Generic Token**. Copy the value — it's shown only once.

## 2. Configure your MCP client

Add a server entry pointing at:

- **URL**: `https://gitgrit.dev/mcp/`
- **Authorization header**: `Bearer YOUR_TOKEN`

Streamable HTTP transport is required. The exact config shape varies by
client; consult your client's docs for the right field name.

## 3. First contact

When the client opens an MCP session, the server returns its
`instructions` field tailored to generic clients — telling the assistant
to call `session_bootstrap` before any tool that takes a `project_id`,
and to call `validate_edit` before every proposed file change.

If your client surfaces server `instructions` to the model context,
that's enough — proceed to step 4.

If your client *doesn't* surface server instructions (the model never
sees them), use the explicit fallback. Type in chat:

> set up GitGrit for this project

The assistant will call `export_setup_files` and the response includes a
ready-to-write rule file path and content. If your client supports rule
files, write the content there; otherwise, paste the file's content as a
system message in your client's prompt configuration.

## 4. Bootstrap and edit

In a project chat, ask:

> what's the compliance status of this project?

The assistant runs `git remote get-url origin`, calls `session_bootstrap`
with both `repo_full_path` and `web_url`, and binds the local clone.
Server-side normalization handles SSH / HTTPS / `.git` / case
differences, so any of these forms hit the same project:

- `git@github.com:acme/backend.git`
- `https://github.com/acme/backend`
- `https://user:tok@github.com/acme/backend.git`

For every proposed edit thereafter, the assistant calls `validate_edit`
with `prior_content` (the file's current content) and `new_content` (the
proposed content). The server reports only the violations this edit
*introduced*.

## HTTP fallback

If your client can't make MCP tool calls but can hit HTTPS endpoints, you
can pull a rule file directly:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://gitgrit.dev/api/setup/cursor/
```

(Or `cline` instead of `cursor`.) The response is plain text — write it
to your editor's rules path manually.

## Troubleshooting

- **`session_bootstrap` returns `error: no_match`.** The local git remote
  doesn't match any project in the workspace this token belongs to.
  Check that the project is registered, and that you're using the right
  token. Read the `candidates` field for near-misses.
- **The assistant ignores the rules.** Your client may not surface
  server `instructions` *and* may not auto-load any rule file. Paste the
  content of `export_setup_files` into a system message yourself.
- **`export_setup_files` returns `error: not_applicable`.** The token is
  Claude-kind. Generate a new generic-kind token.
