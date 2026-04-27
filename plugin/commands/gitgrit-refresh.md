---
description: Reload the active GitGrit policy list for the resolved project.
---

Read the GitGrit session state file to get the resolved `project_id`. Use the Bash tool:

```bash
cat "${XDG_CACHE_HOME:-$HOME/.cache}/gitgrit/$(git rev-parse --absolute-git-dir | sha256sum | cut -c1-16).json" 2>/dev/null
```

If it prints nothing, or `project_id` is null, tell the developer GitGrit is not active for this session and stop.

Otherwise call `gitgrit/get_active_policies_for_project(project_id=<id>)` now — even if you already have policies in context from the session bootstrap, the whole point of this command is to force a fresh fetch from the server in case policies were edited, enabled, or disabled mid-session. Do not satisfy this command from cached bootstrap data.

After the call:

1. **Rewrite the session-state file** with the same `project_id` / `project_name` you read above and `"version": 2`, but flip `policies_loaded` based on the fresh result:
   - If the returned list is empty → `"policies_loaded": false`. Tell the developer "this project still has no active policies linked; enforcement remains OFF."
   - If the returned list is non-empty → `"policies_loaded": true`. Confirm the count and note any policies that changed (added, removed, or with a new `last_execution`) compared to what you had before.

2. The `policies_loaded` flag is what the PreToolUse hook reads to decide whether to remind you to enforce, and what `/gitgrit-check` reads to decide whether to run. Always rewrite it — a session that started empty can become enforcing once a policy is linked, and vice versa.

The HARD RULE from session start still applies: only enforce rules whose literal `{kind, value}` appears in `policies[i].rules`. Do not invent rules from any other source.
