---
description: Run GitGrit enforcement against every file modified since the last commit.
---

First confirm GitGrit is active and has policies loaded for this session — use the Bash tool:

```bash
cat "${XDG_CACHE_HOME:-$HOME/.cache}/gitgrit/$(git rev-parse --absolute-git-dir | sha256sum | cut -c1-16).json" 2>/dev/null
```

If it prints nothing, tell the developer GitGrit is not active for this session and stop.

If it prints a JSON object with `"policies_loaded": false` (or the field is missing / `version` is below 2), tell the developer "no policies are loaded for this session — run /gitgrit-refresh to re-check, or link a policy in the GitGrit UI" and stop. Do not invent a verdict; this command exists to apply real loaded policies, not to substitute for them.

Otherwise (`policies_loaded: true`) extract `project_id` from the same JSON.

Run `git diff --name-only HEAD` to list modified files in the current working tree.

For **each** modified file:

1. Read the file's current content with the Read tool (this is the proposed `new_content` since the working tree already reflects the proposed edit).
2. Run `git show HEAD:<file>` to get the file's content at HEAD (this is `prior_content`). For newly added files, pass `prior_content=null`.
3. Call `gitgrit/validate_edit(project_id=<id>, file_path=<file>, prior_content=<HEAD content>, new_content=<working-tree content>)`.
4. Report any `introduced_violations`: name the policy, quote the matched `matched_substring`, and suggest a fix. Treat `pre_existing_violations_count` as informational only. Surface any `notes` verbatim.

The HARD RULE from session start still applies: only enforce rules whose `{kind, value}` came back from `validate_edit` for this project. No invented rules.
